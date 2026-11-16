"""Bounded best-effort hints; disk logging never runs on a business thread."""
import json
import queue
import threading
import time
import uuid

from .state import OperationLock, atomic_json

_queue=queue.Queue(maxsize=256)
_start=threading.Lock()
_thread=None
KINDS={'mail','calendar','classify','manual-check','manual-reclassify','scheduled-check','calendar-analysis','live-inbox','events'}
ACTIONS={'queued','started','completed','retry_or_failed','published','discarded'}


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


def _run():
    while True:
        root,event=_queue.get()
        try:
            path=root/event['workspace']/'events.json'
            lock=OperationLock(path.with_suffix('.events.lock'))
            if not lock.acquire(False):
                continue
            try:
                try:
                    events=json.loads(path.read_text())
                except FileNotFoundError:
                    events=[]
                atomic_json(path,[*events[-999:],event])
            finally:
                lock.release()
        except Exception:
            pass
        finally:
            _queue.task_done()
