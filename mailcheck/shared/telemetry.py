"""Bounded best-effort hints; disk logging never runs on a business thread.

Two files live under the shared-runtime root:
- ``<workspace>/events.json``: the latest 1000 events per workspace (event log).
- ``metrics.json``: per-minute job counts and duration histograms for 24 hours,
  shared by every process, so monitoring graphs survive the event-log cap.

The writer drains whatever is queued and writes each file once per batch, so a
burst of events costs one rewrite per file instead of one per event.
"""
import json
import queue
import threading
import time
import uuid

from .state import OperationLock, atomic_json

_queue=queue.Queue(maxsize=1024)
_start=threading.Lock()
_thread=None
KINDS={'mail','calendar','classify','manual-check','manual-reclassify','scheduled-check','calendar-analysis','live-inbox','events'}
ACTIONS={'queued','started','completed','retry_or_failed','published','discarded'}
TERMINAL={'completed','retry_or_failed','discarded'}
EVENT_LIMIT=1000
METRIC_MINUTES=24*60
# Job duration histogram upper bounds in seconds; the last bin is open-ended.
DURATION_BOUNDS=(1,2,5,10,30,60,120,300,600)
DURATION_BINS=len(DURATION_BOUNDS)+1
LOCK_WAIT=2.0
# job id -> start time, for jobs this process started. Bounded: a lost
# completion must not grow memory.
_started={}
_STARTED_LIMIT=4096


def duration_bin(seconds):
    for index,bound in enumerate(DURATION_BOUNDS):
        if seconds<=bound:
            return index
    return DURATION_BINS-1


def record(root,workspace,kind,action,job_id):
    global _thread
    if kind not in KINDS or action not in ACTIONS:
        return
    try:
        _queue.put_nowait((root,dict(id=str(uuid.uuid4()),at=time.time(),workspace=workspace,
            component=kind,action=action,job_id=str(job_id),status='degraded' if action=='retry_or_failed' else 'healthy')))
    except queue.Full:
        return
    with _start:
        if _thread is None:
            _thread=threading.Thread(target=_run,daemon=True,name='shared-telemetry')
            _thread.start()


def _duration(event):
    """Seconds since this process saw the job start, for terminal events."""
    key=(event['workspace'],event['component'],event['job_id'])
    if event['action']=='started':
        if len(_started)>=_STARTED_LIMIT:
            _started.pop(next(iter(_started)))
        _started[key]=event['at']
        return None
    if event['action'] in TERMINAL:
        began=_started.pop(key,None)
        if began is not None and event['at']>=began:
            return event['at']-began
    return None


FLUSH_SECONDS=10
# root -> minute -> kind -> {action: count, 'duration': [bins]}; written to
# metrics.json at most every FLUSH_SECONDS, so busy workers do not rewrite the
# 24-hour file for every event.
_pending={}
_last_flush=0.0


def _count(events_by_root):
    for root,items in events_by_root.items():
        minutes=_pending.setdefault(root,{})
        for event,seconds in items:
            row=minutes.setdefault(str(int(event['at']//60)),{}).setdefault(event['component'],{})
            row[event['action']]=row.get(event['action'],0)+1
            if seconds is not None:
                row.setdefault('duration',[0]*DURATION_BINS)[duration_bin(seconds)]+=1


def _int(value):
    return value if type(value) is int and value>=0 else 0


def _merge_metrics(path,additions):
    """Add counts into the shared file; malformed rows are repaired, not fatal."""
    lock=OperationLock(path.with_suffix('.lock'))
    if not lock.acquire(True,LOCK_WAIT):
        return False
    try:
        try:
            data=json.loads(path.read_text())
            minutes=data.get('minutes') if isinstance(data,dict) else None
            if not isinstance(minutes,dict):
                minutes={}
        except (FileNotFoundError,ValueError,OSError):
            minutes={}
        for minute,kinds in additions.items():
            stored=minutes.get(minute)
            if not isinstance(stored,dict):
                stored=minutes[minute]={}
            for kind,counts in kinds.items():
                row=stored.get(kind)
                if not isinstance(row,dict):
                    row=stored[kind]={}
                for action,value in counts.items():
                    if action=='duration':
                        histogram=row.get('duration')
                        if not isinstance(histogram,list) or len(histogram)!=DURATION_BINS:
                            histogram=[0]*DURATION_BINS
                        row['duration']=[_int(a)+b for a,b in zip(histogram,value)]
                    else:
                        row[action]=_int(row.get(action))+value
        cutoff=int(time.time()//60)-METRIC_MINUTES
        minutes={key:value for key,value in minutes.items() if isinstance(key,str) and key.isdigit() and int(key)>cutoff}
        atomic_json(path,{'version':1,'minutes':minutes})
        return True
    finally:
        lock.release()


def _flush_metrics():
    global _last_flush
    _last_flush=time.monotonic()
    for root in list(_pending):
        additions=_pending.pop(root)
        try:
            if not _merge_metrics(root/'metrics.json',additions):
                _requeue(root,additions)
        except Exception:
            _requeue(root,additions)


def _requeue(root,additions):
    """Keep counts for the next flush (bounded to a day of minutes)."""
    minutes=_pending.setdefault(root,{})
    for minute,kinds in additions.items():
        for kind,counts in kinds.items():
            row=minutes.setdefault(minute,{}).setdefault(kind,{})
            for action,value in counts.items():
                if action=='duration':
                    row['duration']=[a+b for a,b in zip(row.get('duration',[0]*DURATION_BINS),value)]
                else:
                    row[action]=row.get(action,0)+value
    if len(minutes)>METRIC_MINUTES:
        for minute in sorted(minutes,key=int)[:len(minutes)-METRIC_MINUTES]:
            del minutes[minute]


def _append_events(path,events):
    lock=OperationLock(path.with_suffix('.events.lock'))
    if not lock.acquire(True,LOCK_WAIT):
        return
    try:
        try:
            existing=json.loads(path.read_text())
            if not isinstance(existing,list):
                existing=[]
        except (FileNotFoundError,ValueError,OSError):
            existing=[]
        atomic_json(path,[*existing,*events][-EVENT_LIMIT:])
    finally:
        lock.release()


def _write(batch,flush=True):
    by_root={}
    for root,event in batch:
        by_root.setdefault(root,[]).append((event,_duration(event)))
    _count(by_root)
    if flush or time.monotonic()-_last_flush>=FLUSH_SECONDS:
        _flush_metrics()
    for root,items in by_root.items():
        workspaces={}
        for event,_seconds in items:
            workspaces.setdefault(event['workspace'],[]).append(event)
        for workspace,events in workspaces.items():
            try:
                _append_events(root/workspace/'events.json',events)
            except Exception:
                pass


def _run():
    while True:
        try:
            # Wake at least once per flush interval so quiet periods still
            # publish counts that arrived just before them.
            batch=[_queue.get(timeout=FLUSH_SECONDS)]
        except queue.Empty:
            if _pending:
                try:
                    _flush_metrics()
                except Exception:
                    pass
            continue
        while len(batch)<256:
            try:
                batch.append(_queue.get_nowait())
            except queue.Empty:
                break
        try:
            _write(batch,flush=False)
        except Exception:
            pass
        finally:
            for _item in batch:
                _queue.task_done()
