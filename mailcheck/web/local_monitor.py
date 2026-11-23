"""Independent, loopback-only operations console for OfferPath."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from http.client import HTTPConnection, HTTPException as HTTPClientError
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import config
from .. import __version__
from .supervisor import origin_state


def independent_snapshot(root, origin, previous=None):
    from ..shared.health_evidence import failure, safe_evidence
    from ..shared.service_health import read_services
    from ..shared.monitoring import read_events, read_rabbit
    from .system_monitoring import database_snapshot
    previous = previous or {}
    workers = read_services(root)
    for lane, variable, default in (('api', 'OFFERPATH_API_WORKERS', 2), ('job-collection', 'OFFERPATH_COLLECTION_WORKERS', 2), ('job-model', 'OFFERPATH_MODEL_WORKERS', 2)):
        try:
            count = min(64, max(1, int(os.environ.get(variable, default))))
        except ValueError:
            count = default
        for index in range(count):
            slot = f'shared-{lane}-{index}'
            workers.setdefault(slot, dict(id=slot, name=slot, status='unknown', detail='No independent health report yet. Restart this worker to enable reporting.'))
    for item in previous.get('components', []):
        if item['id'].startswith(('shared-api-', 'shared-job-')) and item['id'] not in workers:
            workers[item['id']] = {**item, 'status':'unknown', 'detail':'No independent health report yet. Restart this worker to enable reporting.'}
    components = [dict(id='gateway', name='Gateway', status='healthy' if origin == 'ready' else 'degraded' if origin == 'busy' else 'unavailable',
                       scope='local_http_listener',checked_at=time.time(),reason='listener_'+origin,
                       detail='Local HTTP liveness only. Public access, page execution, and workspace requests are checked separately.')]
    components.extend(workers.values())
    job_workers = [item for item in workers.values() if item['id'].startswith('shared-job-')]
    coverage = [item.get('telemetry_status','unknown') if item['status'] in ('healthy','degraded') else 'unknown' for item in job_workers]
    telemetry_status = 'healthy' if coverage and all(status=='healthy' for status in coverage) else 'unavailable' if 'unavailable' in coverage else 'unknown'
    components.append(dict(id='job-telemetry',name='Job telemetry',status=telemetry_status,scope='telemetry_writer_coverage',
                           checked_at=time.time(),reason='writers_responsive' if telemetry_status=='healthy' else 'writer_coverage_incomplete',
                           detail=f'{coverage.count("healthy")}/{len(coverage)} job-worker telemetry writers reporting. Recorded event counts do not prove current observation coverage.'))
    control = database_snapshot(Path(root)/'control.db')
    components.append(dict(id='control-db', name='Control database', **{key:value for key,value in control.items() if key not in ('accounts','outbox')}))
    queues, broker_evidence = [], {}
    if os.environ.get('AMQP_URL'):
        try:
            queues = read_rabbit(os.environ['AMQP_URL'])
            broker_status, detail = 'healthy', 'Independent passive RabbitMQ queue check succeeded.'
        except Exception as exc:
            broker_status, detail = 'unavailable', 'Independent RabbitMQ connection or queue check failed.'
            broker_evidence = failure(exc)
    else:
        broker_status, detail = 'unknown', 'Broker credentials are unavailable to this monitor. Start monitoring from start.bat.'
    components.append(dict(id='rabbitmq', name='RabbitMQ / shared queues', status=broker_status, detail=detail,
                           scope='passive_queue_read',checked_at=time.time(), **broker_evidence))
    workspaces, events = [], []
    try:
        path = Path(root)/'control.db'
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.2) as conn:
            rows = conn.execute('SELECT id,name,root,enabled FROM workspaces ORDER BY id').fetchall()
        components.append(dict(id='workspace-registry',name='Workspace registry',status='healthy',
                               checked_at=time.time(),scope='workspace_inventory',reason='inventory_read',detail=f'{len(rows)} registered workspaces.'))
        def inspect(row):
            wid, name, folder, enabled = row
            try:
                return database_snapshot(Path(folder)/'data'/'mailcheck.db' if folder else config.db_path()) if enabled else dict(status='disabled',detail='Workspace suspended.',accounts=[],outbox=None)
            except (OSError,ValueError,TypeError) as exc:
                return dict(status='unavailable',detail='Workspace database probe failed.',accounts=[],outbox=None,scope='sqlite_read',checked_at=time.time(),**failure(exc))
        with ThreadPoolExecutor(max_workers=8,thread_name_prefix='monitor-db') as executor:
            databases = list(executor.map(inspect,rows))
        for (wid, name, folder, enabled), database in zip(rows,databases):
            components.append(dict(id=wid+':database',name='Workspace database',workspace=wid,
                                   **{key:value for key,value in database.items() if key not in ('accounts','outbox')}))
            workspaces.append(dict(id=wid,name=name,enabled=bool(enabled),accounts=database['accounts'],outbox=database['outbox'],queues=[]))
            events.extend(read_events(root,wid))
    except (OSError,sqlite3.Error,ValueError) as exc:
        components.append(dict(id='workspace-registry',name='Workspace registry',status='unavailable',
                               scope='workspace_inventory',checked_at=time.time(),detail='Workspace inventory could not be read. Coverage is incomplete.',**failure(exc)))
    return dict(checked_at=time.time(), architecture='shared', independent_services=True,
                components=components, workspaces=workspaces, events=sorted(events,key=lambda item:item['at'],reverse=True)[:200],
                global_queues=queues, event_retention=1000)


def fetch_snapshot(port, path='/_internal/origin-monitoring'):
    connection = HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        if response.status != 200:
            raise OSError('Origin service snapshot unavailable')
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Monitoring response exceeded its size limit')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Monitoring response must be an object')
        return result
    finally:
        connection.close()


class Observer:
    def __init__(self, root, origin_port):
        self.root = Path(root)
        self.origin_port = origin_port
        self.lock = threading.Lock()
        self.latest = None
        self.metrics = {}
        self.state = 'unknown'
        self.checked_at = None
        self.outage_since = None
        self.stop = threading.Event()
        self.service_states = {}
        self.public = dict(id='public-site',name='Public site',status='unknown',detail='Waiting for independent public HTTP probe.',scope='public_shell_assets')
        from .monitoring_metrics import QueueHistory
        self.queue_history = QueueHistory()
        self.job_coverage = {}
        try:
            with (self.root/'monitor-job-coverage.json').open('rb') as stream:
                raw=stream.read(100001)
            coverage=json.loads(raw) if len(raw)<=100000 else {}
            now=int(time.time()//60)
            if isinstance(coverage,dict):
                self.job_coverage={int(key):value for key,value in coverage.items() if key.isdigit()
                                   and now-1440<=int(key)<=now and type(value) is bool}
        except (OSError,ValueError):
            pass
        try:
            with (self.root/'monitor-metrics.json').open('rb') as stream:
                raw = stream.read(4*1024*1024+1)
            saved = json.loads(raw) if len(raw)<=4*1024*1024 else {}
            if isinstance(saved,dict):
                self.metrics = {key:value for key,value in saved.items() if key in ('1h','6h','24h')
                                and isinstance(value,dict) and isinstance(value.get('generated_at'),(int,float))
                                and 'buckets' in value and 'summary' in value}
        except (OSError,ValueError):
            pass
        try:
            with (self.root/'monitor-queues.json').open('rb') as stream:
                raw = stream.read(2*1024*1024+1)
            saved = json.loads(raw) if len(raw)<=2*1024*1024 else {}
            if isinstance(saved,dict):
                now = int(time.time()//60)
                for minute,queues in saved.items():
                    if not minute.isdigit() or not now-1440<=int(minute)<=now or not isinstance(queues,dict):
                        continue
                    clean = {kind:values for kind,values in queues.items() if isinstance(kind,str) and isinstance(values,list)
                             and len(values)==3 and all(type(v) is int and 0<=v<10**9 for v in values)}
                    self.queue_history._rows[int(minute)] = clean
        except (OSError,ValueError):
            pass
        self.incidents = []
        self.incidents_dirty = False
        self.incident_path = self.root / 'monitor-incidents.json'
        try:
            with self.incident_path.open('rb') as stream:
                raw = stream.read(200001)
            saved = json.loads(raw) if len(raw) <= 200000 else []
            if isinstance(saved, list):
                self.incidents = [item for item in saved if isinstance(item, dict)
                    and item.get('action') in ('service_failed','service_recovered','service_degraded','service_unknown')
                    and isinstance(item.get('component'),str) and isinstance(item.get('id'),str)
                    and type(item.get('at')) in (int,float) and math.isfinite(item['at'])
                    and item.get('status') in ('healthy','unavailable','degraded','unknown')][-200:]
                self.service_states = {item['component']:item['status'] for item in self.incidents}
        except (OSError,ValueError):
            pass

    def record_service_changes(self, snapshot):
        from ..shared.health_evidence import safe_evidence
        changed = False
        for component in snapshot['components']:
            key, status = component['id'], component['status']
            before = self.service_states.get(key)
            if status not in ('healthy','unavailable','degraded','unknown'):
                continue
            self.service_states[key] = status
            action = ('service_recovered' if status=='healthy' and before in ('unavailable','degraded','unknown') else
                      {'unavailable':'service_failed','degraded':'service_degraded','unknown':'service_unknown'}.get(status) if before!=status else None)
            if action:
                self.incidents.append(dict(dict(id=str(uuid.uuid4()), at=time.time(), workspace='',
                    component=key, action=action, status=status, detail=component.get('detail','')), **safe_evidence(component)))
                changed = True
        self.incidents = self.incidents[-200:]
        self.incidents_dirty = self.incidents_dirty or changed
        if self.incidents_dirty:
            try:
                from ..shared.state import atomic_json
                atomic_json(self.incident_path,self.incidents)
                self.incidents_dirty = False
            except OSError:
                logging.warning('Could not save independent monitoring incident history.')
        snapshot['events'] = sorted(snapshot['events'] + self.incidents, key=lambda item:item['at'],reverse=True)[:200]

    def sample(self):
        state = origin_state('127.0.0.1', self.origin_port)
        snapshot = independent_snapshot(self.root, state, self.latest)
        with self.lock:
            public = dict(self.public)
        if public.get('checked_at') and time.time()-public['checked_at']>90:
            public.update(status='unknown',reason='probe_stale',detail='Public HTTP probe evidence is stale.')
        snapshot['components'].append(public)
        self.record_service_changes(snapshot)
        with self.lock:
            self.state, self.checked_at = state, time.time()
            if state == 'unavailable':
                if self.outage_since is None:
                    self.outage_since = self.checked_at
            elif state == 'ready':
                self.outage_since = None
            if snapshot is not None:
                self.latest = snapshot

    def watch(self):
        while not self.stop.is_set():
            try:
                self.sample()
            except Exception:
                logging.exception('Independent monitoring sample failed')
                with self.lock:
                    self.state = 'unknown'
            self.stop.wait(5)

    def sample_metrics(self):
        from .monitoring_metrics import build_series, read_job_minutes
        from ..shared.state import atomic_json
        with self.lock:
            latest = self.latest or {}
        jobs_current = time.time()-latest.get('checked_at',0)<=15 and any(
            item['id']=='job-telemetry' and item['status']=='healthy' for item in latest.get('components',[]))
        minute=int(time.time()//60)
        self.job_coverage[minute]=self.job_coverage.get(minute,True) and jobs_current
        self.job_coverage={key:value for key,value in self.job_coverage.items() if minute-1440<=key<=minute}
        if time.time()-latest.get('checked_at',0)<=15:
            self.queue_history.record(latest.get('global_queues',[]))
        job_path = self.root/'shared-runtime'/'metrics.json'
        try:
            with job_path.open('rb') as stream:
                raw = stream.read(4*1024*1024+1)
            job_data = json.loads(raw) if len(raw)<=4*1024*1024 else None
            jobs_available = isinstance(job_data,dict) and isinstance(job_data.get('minutes'),dict)
        except (OSError,ValueError):
            jobs_available = False
        for range_key in ('1h','6h','24h'):
            try:
                result = fetch_snapshot(self.origin_port, '/_internal/origin-metrics?range='+range_key)
                if not isinstance(result.get('buckets'),list) or 'summary' not in result or type(result.get('step')) is not int or result['step']<=0 or not isinstance(result.get('jobs'),dict):
                    raise ValueError('Incomplete metrics')
                result = {**result,'source':'gateway','traffic_available':True}
            except (OSError,ValueError,HTTPClientError):
                now = time.time()
                since = int(now//60)-24*60
                result = build_series(range_key,{},read_job_minutes(job_path,since),
                                      self.queue_history.rows(since),now=now,jobs_tracked=jobs_available)
                result.update(source='independent',traffic_available=False)
            result['jobs_current_available'] = jobs_current
            result['jobs_coverage_incomplete'] = False
            for index,start in enumerate(result.get('buckets',[])):
                covered=all(self.job_coverage.get(key) is True for key in range(int(start//60),min(minute,int((start+result['step']-1)//60))+1))
                if covered:
                    continue
                result['jobs_coverage_incomplete'] = True
                for key in ('completed','failed','discarded','queued','p95'):
                    if result.get('jobs',{}).get(key):
                        result['jobs'][key][index] = None
                for stage in result.get('jobs',{}).get('stages',{}).values():
                    for values in stage.values():
                        if isinstance(values,list) and index<len(values):
                            values[index]=None
            with self.lock:
                self.metrics[range_key] = result
        try:
            atomic_json(self.root/'monitor-metrics.json',self.metrics)
            atomic_json(self.root/'monitor-queues.json',self.queue_history.rows(int(time.time()//60)-1440))
            atomic_json(self.root/'monitor-job-coverage.json',self.job_coverage)
        except OSError:
            logging.warning('Could not persist independent metrics history.')

    def watch_public(self):
        from .public_health import public_snapshot
        while not self.stop.is_set():
            result = public_snapshot(os.environ.get('OFFERPATH_PUBLIC_URL',''),Path(__file__).parent/'frontend_dist')
            with self.lock:
                self.public = result
            self.stop.wait(30)

    def watch_metrics(self):
        while not self.stop.is_set():
            try:
                self.sample_metrics()
            except Exception:
                logging.exception('Independent metrics sampling failed')
            self.stop.wait(15)

    def status(self):
        try:
            logs = sorted(p.name for p in (self.root / 'logs').glob('*.log') if p.is_file())
        except OSError:
            logs = []
        with self.lock:
            return dict(origin=self.state, checked_at=self.checked_at, snapshot=self.latest,
                        outage_since=self.outage_since,
                        failed_services=[item['id'] for item in (self.latest or {}).get('components', []) if item['status']=='unavailable'],
                        problem_services=[dict(id=item['id'],status=item['status'],reason=item.get('reason',''))
                                          for item in (self.latest or {}).get('components', []) if item['status'] in ('degraded','unknown')],
                        snapshot_stale=self.latest is None or time.time() - self.latest.get('checked_at', 0) > 15,
                        logs=logs)

    def log_tail(self, name):
        # A filename selected from this fixed directory, never an arbitrary path.
        if Path(name).name != name or not name.endswith('.log'):
            raise HTTPException(404, 'Log not found')
        path = self.root / 'logs' / name
        try:
            if path.is_symlink() or not path.is_file():
                raise HTTPException(404, 'Log not found')
            with path.open('rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 32768))
                return stream.read(32768).decode('utf-8', errors='replace')
        except OSError:
            raise HTTPException(503, 'Log cannot be read. Check access from the server account.') from None


def create_app(root, origin_port=52400):
    observer = Observer(root, origin_port)

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=observer.watch, daemon=True, name='origin-observer')
        thread.start()
        threading.Thread(target=observer.watch_metrics, daemon=True, name='origin-metrics-observer').start()
        threading.Thread(target=observer.watch_public, daemon=True, name='public-http-observer').start()
        try:
            yield
        finally:
            observer.stop.set()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.observer = observer

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        # Host validation prevents DNS rebinding against local diagnostics.
        if request.headers.get('host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'error':'Local monitoring only'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                                 'Content-Security-Policy':"frame-ancestors 'none'"})
        return response

    @app.get('/', response_class=HTMLResponse)
    def page():
        html = (Path(__file__).parent / 'frontend_dist' / 'index.html').read_text(encoding='utf-8')
        return html.replace('<html ', '<html data-local-monitor="true" ', 1)

    from .static_files import CompressedStaticFiles, PortableStaticFiles
    app.mount('/assets', CompressedStaticFiles(PortableStaticFiles(directory=Path(__file__).parent / 'frontend_dist' / 'assets')), name='assets')

    @app.get('/api/admin/system-monitoring')
    def snapshot():
        with observer.lock:
            if observer.latest is None:
                raise HTTPException(503, 'Waiting for the first OfferPath service snapshot.')
            stale = time.time() - observer.latest.get('checked_at', 0) > 15
            return {**observer.latest, 'observer_origin':observer.state, 'observer_stale':stale}

    @app.get('/api/admin/system-monitoring/metrics')
    def metrics(range: str = '1h'):
        if range not in ('1h', '6h', '24h'):
            raise HTTPException(422, 'Choose 1h, 6h or 24h.')
        with observer.lock:
            result = observer.metrics.get(range)
            if result is None:
                raise HTTPException(503, 'Waiting for recorded metrics from OfferPath.')
            return {**result, 'observer_stale':time.time() - result.get('generated_at', 0) > 90}

    @app.get('/api/status')
    def status():
        return observer.status()

    @app.get('/health')
    def health():
        return {'service':'offerpath-local-monitor', 'version':__version__, 'pid':os.getpid()}

    @app.get('/api/log')
    def log(name: str):
        return {'text': observer.log_tail(name)}

    return app


def stop_existing_monitor(port):
    """Stop only the verified monitoring module listening on the requested local port."""
    if sys.platform != 'win32':
        raise RuntimeError('Stop the previous monitoring process before starting the updated console.')
    script = (
        f"$listeners=Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction Stop; "
        "$ids=@($listeners | Select-Object -ExpandProperty OwningProcess -Unique); "
        "foreach($monitorId in $ids) { "
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=$monitorId\"; "
        r"if (!$p -or $p.CommandLine -notmatch '(?i)-m\s+mailcheck\.web\.local_monitor(?:\s|$)') "
        "{ throw 'The listener is not a recognized OfferPath monitoring process.' }; "
        "Stop-Process -Id $monitorId -ErrorAction Stop }"
    )
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=52401)
    parser.add_argument('--origin-port', type=int, default=52400)
    parser.add_argument('--ensure', action='store_true')
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    if args.ensure or args.restart:
        def running():
            connection = HTTPConnection('127.0.0.1', args.port, timeout=1)
            try:
                connection.request('GET', '/health')
                response = connection.getresponse()
                value = json.loads(response.read(1024)) if response.status == 200 else {}
                return value if isinstance(value, dict) and value.get('service') == 'offerpath-local-monitor' else None
            except (OSError, ValueError, HTTPClientError):
                return False
            finally:
                connection.close()
        existing = running()
        if existing and (args.restart or existing.get('version') != __version__):
            print('Replacing the outdated monitoring process…', flush=True)
            try:
                stop_existing_monitor(args.port)
            except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
                print(f'Could not restart the existing monitor ({type(error).__name__}). Run monitor.bat from the original server account or an Administrator terminal.', file=sys.stderr)
                return 1
            for _ in range(30):
                if not running():
                    break
                time.sleep(.2)
            else:
                print('The previous monitor has not stopped. No replacement was started.', file=sys.stderr)
                return 1
            existing = None
        if existing:
            print(f'Independent monitoring at http://127.0.0.1:{args.port}', flush=True)
            return
        folder = config.control_dir() / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'local-monitor.log').open('ab') as output:
            flags = {}
            if sys.platform == 'win32':
                flags['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                flags['start_new_session'] = True
            process = subprocess.Popen([sys.executable, '-m', 'mailcheck.web.local_monitor',
                              '--port', str(args.port), '--origin-port', str(args.origin_port)],
                             stdin=subprocess.DEVNULL, stdout=output, stderr=output, **flags)
        for _ in range(30):
            current = running()
            if current and current.get('version') == __version__:
                print(f'Independent monitoring at http://127.0.0.1:{args.port}', flush=True)
                return
            if process.poll() is not None:
                break
            time.sleep(.2)
        print(f'Monitor startup failed. See {folder / "local-monitor.log"}', file=sys.stderr)
        return 1
    from .server import run
    run(create_app(config.control_dir(), args.origin_port), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    raise SystemExit(main())
