"""Server-issued manual job provenance, kept out of broker messages."""
from contextlib import suppress
import time
import uuid

from ..workspaces import WorkspaceContext
from .broker import RabbitBroker
from .state import JobState, OperationLock, atomic_json, runtime_root
from .manual import pending_dispatch

QUEUED_MESSAGE = 'Queued for a shared worker'


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
        if pending_dispatch(store.root/'shared-runtime',workspace_id,status):
            raise BlockingIOError('A check is already queued or waiting to retry.')
        if status.get('running') and time.time()-status.get('queued_at',0)<120:
            raise BlockingIOError('A check is already queued or running.')
        broker = RabbitBroker(url,workspace_id)
        try:
            # Establish the channel before reserving the workspace. No delivery
            # can exist when this initial connection or topology setup fails.
            broker.process_events()
            if not job_lock.acquire(False):
                raise BlockingIOError('A check is already running.')
            try:
                dispatch = str(uuid.uuid4())
                path = store.root/'shared-runtime'/'dispatch'/f'{dispatch}.json'
                atomic_json(path,dict(workspace_id=workspace_id,kind=kind,token=token,body=parsed,
                                      expires=time.time()+7200,state='queued'))
                state.update(running=True,message=QUEUED_MESSAGE,detail='',ok=True,
                             queued_at=time.time(),stage_started=None,job_id=dispatch)
            finally:
                job_lock.release()
            try:
                broker.enqueue(kind,0,'manual',dispatch_id=dispatch,job_id=dispatch)
            except Exception:
                # A lost confirm can race with execution. Update only the
                # original queued message and leave the operation result alone.
                with state.lock:
                    current = state.snapshot()
                    if current.get('job_id') == dispatch and current['running'] and current['message'] == QUEUED_MESSAGE:
                        atomic_json(state.path, {**current,
                            'message': 'Queue confirmation unavailable; check status before retrying.'})
                raise
        finally:
            with suppress(Exception):
                broker.close()
    return {'ok':True,'job_id':dispatch,'queued':True}
