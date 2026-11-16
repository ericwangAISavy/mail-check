"""Bounded RabbitMQ consumers and one same-host reconciliation coordinator.

No application schema changes. All additional coordination lives under
control_root/shared-runtime; normal business operations use existing tables.
"""
from contextlib import contextmanager, ExitStack
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .. import config, db, interviews, mail_checkpoints, pipeline, prefilter
from ..llm import PROMPT_VERSION
from ..models import Classification
from ..realtime import storage
from ..realtime.runtime import Runtime, AccountDisabled, WorkDeferred
from ..realtime.graph import GraphSubscriptions
from ..sources.base import collection_scope
from ..workspaces import WorkspaceContext, bind_workspace, bind_commit_guard, copy_context
from .broker import RabbitBroker, PendingCapacityError
from .state import JobState, OperationLock, account_lease, atomic_json, runtime_root

log = logging.getLogger(__name__)


class ExistingRegistry(storage.Registry):
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        # mode=rw prevents accidentally creating an empty subscription database.
        conn = sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def prepare_registry(root):
    path=root/'realtime.db'
    with OperationLock(root/'shared-runtime'/'registry-init.lock'):
        if not path.exists():
            # Fresh file only, using the existing registry schema. Never run
            # Registry's additive migration against an existing installation.
            storage.Registry(path)
    return ExistingRegistry(path)


class AccountBroker:
    def __init__(self, context, url):
        self.context, self.url = context, url

    def lease(self, account_id, *, lane='collection'):
        return account_lease(self.context, account_id, lane)

    def enqueue(self, kind, account_id, reason='reconcile'):
        broker = RabbitBroker(self.url, self.context.workspace_id)
        try:
            return broker.enqueue_unique(kind, account_id, reason,
                coordination_root=self.context.control_root/'shared-runtime')
        finally:
            broker.close()


def mail_collection_since(path, mailbox, started, lookback_days):
    """Reject invalid/future runtime stamps without losing valid catch-up bounds."""
    fallback = started-timedelta(days=max(1, lookback_days))
    try:
        previous = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return fallback
    if not isinstance(previous, dict) or previous.get('mailbox') != mailbox:
        return fallback
    for field in ('pending', 'checked'):
        value = previous.get(field)
        if not isinstance(value, str):
            continue
        try:
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None or instant.utcoffset() is None or instant > started:
                continue
            instant = instant.astimezone(timezone.utc)
            return instant if field == 'pending' else instant-timedelta(minutes=3)
        except (ValueError, OverflowError):
            continue
    return fallback


class WorkspaceOperations(Runtime):
    def __init__(self, context, url):
        # Deliberately do not call Runtime.__init__: it initializes legacy
        # realtime checkpoint tables. Shared checkpoints are runtime files.
        self.context = context
        self.workspace_id = context.workspace_id
        self.db_path = config.db_path()
        self.config_loader = config.load
        self.broker = AccountBroker(context, url)
        self.job_lock = OperationLock(runtime_root(context)/'job.lock')
        self._stop = threading.Event()

    def collect_mail(self, account_id, processing=None):
        with self.broker.lease(account_id) as lease:
            if not lease:
                raise WorkDeferred('Collection is busy')
            with db.session() as conn:
                account = self._account(conn, account_id)
                if account is None:
                    return
                check = self._guard(conn, account_id, lease, processing)
                check()
                cfg = config.load()
                started = datetime.now(timezone.utc)
                mailbox = mail_checkpoints.mailbox_key(account)
                checkpoint = runtime_root(self.context)/f'mail-{account_id}.json'
                since = mail_collection_since(checkpoint, mailbox, started, cfg.check.lookback_days)
                # Preserve catch-up lower bound across provider outages/crashes.
                atomic_json(checkpoint, {'mailbox':mailbox,'pending':since.isoformat()})
                with collection_scope(lambda _: check()):
                    messages = pipeline.fetch_account(account, since, cfg)
                for message in messages:
                    check()
                    pk = db.upsert_message(conn,message)
                    if db.get_cached(conn,pk,None) is not None:
                        continue
                    rule = prefilter.apply(message,cfg.prefilter_rules)
                    if rule:
                        db.save_classification(conn,pk,rule,pipeline.RULE_MODEL,PROMPT_VERSION,commit=False)
                    elif not conn.execute('SELECT 1 FROM classifications WHERE message_pk=?',(pk,)).fetchone():
                        db.save_classification(conn,pk,Classification('unclassified',retryable=True,
                            summary='Waiting for classification.'),'realtime-pending',PROMPT_VERSION,commit=False)
                check()
                conn.commit()
                atomic_json(checkpoint, {'mailbox':mailbox,'checked':started.isoformat()})
                storage.set_status(conn,account_id,last_sync=time.time())
                pending = self._pending(conn,account)
            if pending:
                try:
                    self.broker.enqueue('classify',account_id)
                except PendingCapacityError:
                    # Pending classifications are already durable in SQLite.
                    # Finish/ACK this mail job so its marker frees a quota slot;
                    # otherwise a full set of mail hints could block every
                    # classification hint forever. Reconciliation retries it.
                    pass


def publish_outbox(conn, broker, workspace_id):
    rows = storage.pending_outbox(conn)
    if rows:
        broker.publish(sorted({row['topic'] for row in rows}),max(row['id'] for row in rows),workspace_id)
        storage.acknowledge_outbox(conn,[row['id'] for row in rows])
        conn.commit()
        from ..workspaces import current_workspace
        context=current_workspace()
        if context:
            from .telemetry import record
            record(context.control_root/'shared-runtime',workspace_id,'events','published',max(row['id'] for row in rows))


def finish_manual(fields, root):
    """Release terminal UI state only when it still describes this delivery."""
    if fields['kind'] not in {'manual-check','manual-reclassify'}:
        return
    state=JobState(root/fields['workspace_id']/'job.json')
    with state.lock:
        status=state.snapshot()
        if status.get('job_id')==fields['id'] and status.get('running'):
            atomic_json(state.path,{**status,'running':False,'ok':False,
                'message':'Queued check was cancelled or exhausted its retry limit.',
                'detail':'','stage_started':None,'completion_id':status['completion_id']+1})
    dispatch=fields.get('dispatch_id')
    if dispatch and str(uuid.UUID(dispatch))==dispatch:
        (root/'dispatch'/f'{dispatch}.json').unlink(missing_ok=True)


def _dispatch_record(reader, fields):
    dispatch = fields.get('dispatch_id')
    if not dispatch:
        raise PermissionError('Manual dispatch authorization is missing')
    try:
        if str(uuid.UUID(dispatch)) != dispatch:
            raise ValueError('Invalid dispatch')
        path = reader.root/'shared-runtime'/'dispatch'/f'{dispatch}.json'
        record = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        raise PermissionError('Manual dispatch authorization is unavailable') from None
    if (record['workspace_id'] != fields['workspace_id'] or record['kind'] != fields['kind']
            or record['expires'] < time.time()):
        raise PermissionError('Manual dispatch authorization expired or mismatched')
    reader.validate_dispatch(record['token'],fields['workspace_id'],read_only=True)
    return record


def execute_job(reader, legacy_paths, fields, *, handler=None):
    from .manual import read_dispatch,dispatch_path,bind_manual_job,update_status,complete_manual,retry_manual,pending_dispatch
    if fields['kind'] not in {'manual-check','manual-reclassify'}:
        if fields['kind'] in {'scheduled-check','calendar-analysis','live-inbox'} and pending_dispatch(reader.root/'shared-runtime',fields['workspace_id']):
            raise WorkDeferred('A manual check owns the workspace queue')
        return _execute_job(reader,legacy_paths,fields,handler=handler)
    root=reader.root/'shared-runtime'
    path=dispatch_path(root,fields.get('dispatch_id'))
    lock=OperationLock(path.with_suffix('.lock'))
    if not lock.acquire(False):
        raise WorkDeferred('Manual delivery is already executing')
    try:
        record=read_dispatch(root,fields)
        if record.get('state')=='succeeded':
            complete_manual(root,fields,record)
            return
        state=JobState(root/fields['workspace_id']/'job.json').snapshot()
        if state.get('job_id') not in (None,fields['id']):
            raise PermissionError('Manual delivery has been superseded')
        atomic_json(path,{**record,'state':'running'})
        update_status(root,fields,running=True)
        with bind_manual_job(fields):
            try:
                result=_execute_job(reader,legacy_paths,fields,handler=handler)
            except Exception:
                retry_manual(root,fields)
                raise
            complete_manual(root,fields,record)
            return result
    finally:
        lock.release()


def _execute_job(reader, legacy_paths, fields, *, handler=None):
    workspace = reader.workspace(fields['workspace_id'])
    context = WorkspaceContext.from_record(workspace,legacy_paths,reader.root)
    with bind_workspace(context):
        kind = fields['kind']
        manual = kind in {'manual-check','manual-reclassify'}
        record = _dispatch_record(reader,fields) if manual else None
        account_snapshot=[]
        scoped=manual or kind in {'scheduled-check','live-inbox','calendar-analysis'}
        if scoped and config.db_path().is_file():
            with sqlite3.connect(config.db_path().resolve().as_uri()+'?mode=ro',uri=True) as conn:
                if kind == 'manual-reclassify':
                    conn.row_factory = sqlite3.Row
                    body = record['body']
                    waiting = db.messages_in_categories(conn, [pipeline.UNCLASSIFIED],
                        pks=body.get('pks') or None, account_label=body.get('account'),
                        since_iso=(datetime.now(timezone.utc)-timedelta(days=body['days'])).isoformat()
                            if body.get('days') else None)
                    targets = {row['account_id'] for row in waiting}
                    # Empty pks means "all" to the legacy operation. A negative
                    # sentinel keeps an empty resolved selection empty instead.
                    record = {**record, 'body': {**body,
                        'pks': [row['pk'] for row in waiting] or [-1]}}
                    account_snapshot = [tuple(row) for row in conn.execute(
                        'SELECT id,label,email,provider FROM accounts') if row['id'] in targets]
                else:
                    account_snapshot=conn.execute('SELECT id,label,email,provider FROM accounts WHERE enabled=1').fetchall()
                    label=record['body'].get('account') if record else None
                    if label:
                        account_snapshot=[row for row in account_snapshot if row[1]==label]

        def guard():
            current = reader.workspace(context.workspace_id)
            if current.get('root') != workspace.get('root'):
                raise AccountDisabled('Workspace changed')
            if scoped and account_snapshot:
                with sqlite3.connect(config.db_path().resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as conn:
                    for account in account_snapshot:
                        current_account=conn.execute('SELECT id,label,email,provider FROM accounts WHERE id=? AND enabled=1',(account[0],)).fetchone()
                        if current_account != account:
                            raise AccountDisabled('Selected account was disabled, removed or replaced')
            if manual:
                reader.validate_dispatch(record['token'],context.workspace_id,read_only=True)
            elif kind in {'scheduled-check','live-inbox'}:
                if not config.load().watch.auto_check:
                    raise AccountDisabled('Scheduled checks disabled')
            elif kind != 'calendar-analysis':
                # A separate reader observes opt-out/revocation even when the
                # operation's writer connection retains an earlier snapshot.
                conn = sqlite3.connect(config.db_path().resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
                try:
                    enabled = conn.execute('SELECT 1 FROM accounts a JOIN realtime_accounts r ON r.account_id=a.id '
                        'WHERE a.id=? AND a.enabled=1 AND r.enabled=1',(fields['account_id'],)).fetchone()
                    if not enabled:
                        raise AccountDisabled('Automatic account updates disabled')
                finally:
                    conn.close()

        guard()
        with ExitStack() as stack:
            if scoped:
                lane='classification' if kind in {'manual-reclassify','calendar-analysis'} else 'collection'
                for account in sorted(account_snapshot):
                    lease=stack.enter_context(account_lease(context,account[0],lane))
                    if lease is None:
                        raise WorkDeferred('An account operation is already running')
            stack.enter_context(bind_commit_guard(guard))
            if handler:
                return handler(context,fields)
            if manual or kind in {'scheduled-check','calendar-analysis','live-inbox'}:
                from ..web import app as web
                if kind=='live-inbox':
                    if not web._resume_live_inbox(config.load()):
                        if web._live_inbox.due():
                            raise WorkDeferred('Workspace check is busy')
                    return
                if not web._job_lock.acquire(False):
                    raise WorkDeferred('Workspace check is busy')
                try:
                    if kind == 'manual-reclassify':
                        web._run_reclassify(web.ReclassifyBody.model_validate(record['body']))
                    elif kind == 'calendar-analysis':
                        web._run_calendar_analysis()
                    else:
                        body = web.CheckBody.model_validate(record['body'] if manual else {})
                        web._run_check(body,include_calendar=kind=='scheduled-check')
                    if not web._job.get('ok',True):
                        raise RuntimeError('Workspace operation reported failure; retrying safely')
                finally:
                    if web._job_lock.locked():
                        web._job_lock.release()
            else:
                operations = WorkspaceOperations(context,os.environ['AMQP_URL'])
                action = {'mail':operations.collect_mail,'calendar':operations.collect_calendar,
                          'classify':operations.classify_account}[kind]
                action(fields['account_id'])


class Coordinator:
    def __init__(self, reader, legacy_paths, url):
        self.reader,self.legacy_paths,self.url = reader,legacy_paths,url
        self.stop = threading.Event()
        self.due = {}
        self.cursor = {}

    def run(self):
        # A second coordinator never steals ownership from a live first one.
        lock = OperationLock(self.reader.root/'shared-runtime'/'coordinator.lock')
        if not lock.acquire(False):
            return
        try:
            prepare_registry(self.reader.root)
            subscriptions=threading.Thread(target=self.subscriptions_run,daemon=True,name='shared-subscriptions')
            subscriptions.start()
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception:
                    log.warning('Shared reconciliation is unavailable; retrying.')
                self.stop.wait(1)
            subscriptions.join()
        finally:
            lock.release()

    def subscriptions_run(self):
        while not self.stop.is_set():
            try:
                for workspace in self.reader.enabled_workspaces():
                    if self.stop.is_set():
                        break
                    context=WorkspaceContext.from_record(workspace,self.legacy_paths,self.reader.root)
                    with bind_workspace(context):
                        if not config.db_path().is_file():
                            continue
                        try:
                            with db.session() as conn:
                                accounts=db.list_accounts(conn)
                                enabled=set(storage.enabled_accounts(conn))
                                cfg=config.load()
                            registry=ExistingRegistry(self.reader.root/'realtime.db')
                            GraphSubscriptions(registry,workspace['id'],os.environ.get('OFFERPATH_PUBLIC_URL','')).sync(accounts,enabled,cfg)
                        except Exception:
                            log.warning('Workspace subscription maintenance unavailable; polling continues.')
            except Exception:
                log.warning('Workspace subscription discovery unavailable; retrying.')
            self.stop.wait(60)

    def tick(self):
        broker = RabbitBroker(self.url)
        live = set()
        try:
            for _ in range(100):
                notice=broker.claim_dead_notice()
                if notice is None:
                    break
                tag,fields=notice
                broker.abandon_unique(fields,self.reader.root/'shared-runtime')
                finish_manual(fields,self.reader.root/'shared-runtime')
                broker.ack(tag)
            for workspace in self.reader.enabled_workspaces():
                wid = workspace['id']
                live.add(wid)
                context = WorkspaceContext.from_record(workspace,self.legacy_paths,self.reader.root)
                with bind_workspace(context):
                    if not config.db_path().is_file():
                        continue
                    try:
                        with db.session() as conn:
                            # Existing trigger switch; no DDL/schema migration.
                            storage.set_publishing(conn,True)
                            publish_outbox(conn,broker,wid)
                            accounts = db.list_accounts(conn,only_enabled=True)
                            enabled = set(storage.enabled_accounts(conn))
                            cfg = config.load()
                            now = time.monotonic()
                            def admit(kind,account_id):
                                try:
                                    broker.enqueue_unique(kind,account_id,'reconcile',workspace_id=wid,
                                        coordination_root=self.reader.root/'shared-runtime',dirty_existing=False)
                                    return True
                                except PendingCapacityError:
                                    return False
                            from .state import ScheduleState
                            schedule=ScheduleState(runtime_root(context)/'schedule.json')
                            if not cfg.watch.auto_check:
                                schedule.update(next_due=None)
                            elif schedule['next_due'] is None:
                                schedule.update(next_due=time.time()+cfg.watch.interval_minutes*60)
                            elif time.time()>=schedule['next_due']:
                                if admit('scheduled-check',0):
                                    schedule.update(next_due=time.time()+cfg.watch.interval_minutes*60)
                            from ..calendar_queue import due
                            if cfg.is_llm_ready() and due(conn) and now>=self.due.get((wid,0,'calendar-analysis'),0):
                                if admit('calendar-analysis',0):
                                    self.due[(wid,0,'calendar-analysis')]=now+120
                            from .live_inbox import SharedLiveInbox
                            demand=SharedLiveInbox(runtime_root(context)/'live-inbox.json')
                            if cfg.watch.auto_check and cfg.is_llm_ready() and demand.due() and now>=self.due.get((wid,0,'live-inbox'),0):
                                if admit('live-inbox',0):
                                    self.due[(wid,0,'live-inbox')]=now+30
                            accounts=[account for account in accounts if account.id in enabled]
                            if accounts:
                                position=self.cursor.get(wid,0)%len(accounts)
                                accounts=accounts[position:]+accounts[:position]
                                self.cursor[wid]=(position+1)%len(accounts)
                            for account in accounts:
                                kinds=['mail']+(['calendar'] if account.provider=='outlook' else [])
                                if WorkspaceOperations(context,self.url)._pending(conn,account):
                                    kinds.append('classify')
                                for kind in kinds:
                                    key=(wid,account.id,kind)
                                    if now>=self.due.get(key,0) and admit(kind,account.id):
                                        self.due[key]=now+(30 if kind=='mail' and account.provider!='outlook' else 120)
                    except Exception:
                        log.warning('Workspace background coordination unavailable; retrying.')
            self.due={key:value for key,value in self.due.items() if key[0] in live}
            self.cursor={key:value for key,value in self.cursor.items() if key in live}
        finally:
            broker.close()


class Consumer:
    def __init__(self, reader, legacy_paths, url, lane):
        self.reader,self.legacy_paths,self.url = reader,legacy_paths,url
        self.kinds = ('mail','calendar') if lane=='collection' else ('classify','manual-check','manual-reclassify','scheduled-check','calendar-analysis','live-inbox')
        self.stop = threading.Event()
        self.inflight = False

    def run(self):
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='shared-operation') as executor:
            while not self.stop.is_set():
                broker = RabbitBroker(self.url)
                try:
                    while not self.stop.is_set():
                        found = False
                        for kind in self.kinds:
                            if self.stop.is_set():
                                break
                            delivery = broker.claim(kind)
                            if delivery is None:
                                continue
                            found = self.inflight = True
                            tag,fields = delivery
                            from .telemetry import record
                            record(self.reader.root/'shared-runtime',fields['workspace_id'],kind,'started',fields['id'])
                            future = executor.submit(execute_job,self.reader,self.legacy_paths,fields)
                            # Keep connection heartbeat active during slow providers/models.
                            disconnected = False
                            while not future.done():
                                try:
                                    broker.process_events(0.1)
                                except Exception:
                                    disconnected = True
                                    future.result()  # Retain operation locks until completion.
                                    break
                            try:
                                future.result()
                            except (AccountDisabled,PermissionError):
                                if not disconnected:
                                    broker.abandon_unique(fields,self.reader.root/'shared-runtime')
                                    finish_manual(fields,self.reader.root/'shared-runtime')
                                    broker.ack(tag)
                                    record(self.reader.root/'shared-runtime',fields['workspace_id'],kind,'discarded',fields['id'])
                            except (WorkDeferred,PendingCapacityError):
                                if not disconnected:
                                    broker.defer(tag,fields)
                            except Exception as exc:
                                log.warning('Shared operation failed: workspace=%s account=%s kind=%s attempt=%s error=%s',
                                    fields['workspace_id'], fields['account_id'], kind, fields['attempt']+1, type(exc).__name__)
                                if not disconnected:
                                    broker.fail(tag,fields)
                                    record(self.reader.root/'shared-runtime',fields['workspace_id'],kind,'retry_or_failed',fields['id'])
                                    if fields['attempt']+1>=5:
                                        broker.abandon_unique(fields,self.reader.root/'shared-runtime')
                                        finish_manual(fields,self.reader.root/'shared-runtime')
                            else:
                                if not disconnected:
                                    broker.complete_unique(fields,self.reader.root/'shared-runtime')
                                    broker.ack(tag)
                                    record(self.reader.root/'shared-runtime',fields['workspace_id'],kind,'completed',fields['id'])
                            finally:
                                self.inflight = False
                            if disconnected:
                                raise ConnectionError('Broker connection lost')
                        if not found:
                            broker.process_events(0.2)
                except Exception:
                    log.warning('Shared job transport unavailable; reconnecting.')
                    self.stop.wait(1)
                finally:
                    self.inflight = False
                    try:
                        broker.close()
                    except Exception:
                        pass


def main():
    import argparse
    import secrets
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI,Request,HTTPException
    from .control import ControlReader
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--lane',choices=('collection','model'),required=True)
    args=parser.parse_args()
    original=Path(os.environ['OFFERPATH_LEGACY_CONFIG_PATH'])
    legacy=(original,Path(os.environ['OFFERPATH_LEGACY_DB_PATH']),original.parent/'web-auth.json')
    reader=ControlReader(Path(os.environ['OFFERPATH_CONTROL_ROOT']),legacy)
    consumer=Consumer(reader,legacy,os.environ['AMQP_URL'],args.lane)
    coordinator=Coordinator(reader,legacy,os.environ['AMQP_URL']) if os.environ.get('OFFERPATH_COORDINATOR')=='1' else None
    @asynccontextmanager
    async def lifespan(app):
        threads=[threading.Thread(target=consumer.run,daemon=True)]
        if coordinator:
            threads.append(threading.Thread(target=coordinator.run,daemon=True))
        for thread in threads:
            thread.start()
        yield
        consumer.stop.set()
        if coordinator:
            coordinator.stop.set()
        # Drain instead of terminating active admin operations.
        import asyncio
        for thread in threads:
            await asyncio.to_thread(thread.join)
    app=FastAPI(lifespan=lifespan)
    @app.get('/_internal/ready')
    def ready(request:Request):
        if not secrets.compare_digest(request.headers.get('x-offerpath-worker',''),os.environ['OFFERPATH_WORKER_TOKEN']):
            raise HTTPException(403)
        return {'ready':True,'inflight':consumer.inflight}
    from ..workspace_workers import InstanceLock
    from .lifecycle import supervise
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False))
    def stop_accepting():
        consumer.stop.set()
        if coordinator:
            coordinator.stop.set()
    process_lock=reader.root/'shared-runtime'/'processes'/f"{os.environ['OFFERPATH_WORKER_ID']}.lock"
    process_lock.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with InstanceLock(process_lock):
        stop_watch=supervise(server,stop_accepting)
        try:
            server.run()
        finally:
            stop_watch()


if __name__=='__main__':
    main()
