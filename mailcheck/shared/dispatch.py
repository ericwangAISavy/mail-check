"""Server-issued manual job provenance, kept out of broker messages."""
import json
from pathlib import Path
import time
import uuid

from ..workspaces import WorkspaceContext
from .broker import RabbitBroker
from .state import JobState, OperationLock, atomic_json, runtime_root


def submit_manual(store, legacy_paths, workspace_id, token, kind, body, url):
    from ..web.app import CheckBody, ReclassifyBody
    model = CheckBody if kind=='manual-check' else ReclassifyBody
    parsed = model.model_validate_json(body).model_dump(mode='json')
    store.validate_dispatch(token,workspace_id,read_only=True)
    context = WorkspaceContext.from_record(store.workspace(workspace_id),legacy_paths,store.root)
    state = JobState(runtime_root(context)/'job.json')
    with OperationLock(runtime_root(context)/'submit.lock'):
        job_lock=OperationLock(runtime_root(context)/'job.lock')
        if not job_lock.acquire(False):
            raise BlockingIOError('A check is already running.')
        job_lock.release()
        status = state.snapshot()
        if status.get('running') and time.time()-status.get('queued_at',0)<120:
            raise BlockingIOError('A check is already queued or running.')
        dispatch = str(uuid.uuid4())
        path = store.root/'shared-runtime'/'dispatch'/f'{dispatch}.json'
        atomic_json(path,dict(workspace_id=workspace_id,kind=kind,token=token,body=parsed,
                              expires=time.time()+7200))
        state.update(running=True,message='Queued for a shared worker',detail='',ok=True,
                     queued_at=time.time(),stage_started=None,job_id=dispatch)
        broker = RabbitBroker(url,workspace_id)
        try:
            broker.enqueue(kind,0,'manual',dispatch_id=dispatch,job_id=dispatch)
        except Exception:
            # An uncertain confirm may already have accepted the message.
            # Keep authorization until expiry rather than destroying accepted work.
            state.update(message='Queue confirmation unavailable; check status before retrying.',ok=False)
            raise
        finally:
            broker.close()
    return {'ok':True,'job_id':dispatch,'queued':True}
