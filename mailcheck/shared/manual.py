"""Private manual-dispatch receipts and queue ownership, outside application DBs."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import time
import uuid

from .state import JobState, atomic_json

_current=ContextVar('shared_manual_job',default=None)
TERMINAL={'succeeded','cancelled','failed'}


def current_manual_job():
    return _current.get()


@contextmanager
def bind_manual_job(fields):
    token=_current.set(fields)
    try:
        yield
    finally:
        _current.reset(token)


def dispatch_path(root,identity):
    if not isinstance(identity,str) or str(uuid.UUID(identity))!=identity:
        raise PermissionError('Invalid manual dispatch identity')
    return root/'dispatch'/f'{identity}.json'


def read_dispatch(root,fields):
    try:
        identity=fields['dispatch_id']
        if identity!=fields['id']:
            raise ValueError('Dispatch identity mismatch')
        record=json.loads(dispatch_path(root,identity).read_text())
        if record['workspace_id']!=fields['workspace_id'] or record['kind']!=fields['kind']:
            raise ValueError('Dispatch scope mismatch')
        if record.get('state') not in TERMINAL and record['expires']<time.time():
            raise ValueError('Dispatch expired')
        return record
    except (KeyError,OSError,ValueError,TypeError):
        raise PermissionError('Manual dispatch authorization unavailable') from None


def pending_dispatch(root,workspace,status=None):
    status=status or JobState(root/workspace/'job.json').snapshot()
    identity=status.get('job_id')
    if not identity:
        return None
    try:
        record=json.loads(dispatch_path(root,identity).read_text())
        if (record['workspace_id']==workspace and record.get('state') not in TERMINAL
                and record['expires']>time.time()):
            return identity,record
    except (OSError,ValueError,TypeError,KeyError,PermissionError):
        pass
    return None


def update_status(root,fields,**changes):
    state=JobState(root/fields['workspace_id']/'job.json')
    with state.lock:
        current=state.snapshot()
        if current.get('job_id') not in (None,fields['id']):
            return
        atomic_json(state.path,{**current,'job_id':fields['id'],**changes})


def retry_manual(root,fields):
    record=read_dispatch(root,fields)
    if record.get('state') in TERMINAL:
        return
    atomic_json(dispatch_path(root,fields['id']),{**record,'state':'retry'})
    update_status(root,fields,running=True,message='Waiting for the shared worker to retry',
                  stage_started=None)


def complete_manual(root,fields,record):
    # Persist success before AMQP acknowledgment. Lost acknowledgments can then
    # be acknowledged again without invoking the provider or model again.
    atomic_json(dispatch_path(root,fields['id']),dict(workspace_id=fields['workspace_id'],
        kind=fields['kind'],expires=record['expires'],state='succeeded'))
    state=JobState(root/fields['workspace_id']/'job.json')
    with state.lock:
        current=state.snapshot()
        if current.get('job_id') in (None,fields['id']) and current.get('running'):
            atomic_json(state.path,{**current,'job_id':fields['id'],'running':False,'ok':True,
                'stage_started':None,'completion_id':current['completion_id']+1})
