"""Process-owned health evidence readable without a working gateway."""
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import math
from urllib.error import HTTPError, URLError
from .health_evidence import failure, safe_evidence
from urllib.request import Request, ProxyHandler, build_opener

SLOT = re.compile(r'shared-(?:api|job-collection|job-model)-[0-9]+')
DEPENDENCIES={'coordinator':'Background coordination','subscriptions':'Microsoft subscriptions'}


def dependency_reports(value):
    if not isinstance(value,dict):return {}
    return {key:{**safe_evidence(item),'status':item['status']} for key,item in value.items()
            if key in DEPENDENCIES and isinstance(item,dict) and item.get('status') in ('healthy','degraded','unknown','unavailable')}


def report_service(server):
    root = os.environ.get('OFFERPATH_CONTROL_ROOT')
    slot = os.environ.get('OFFERPATH_WORKER_ID', '')
    if not root or not SLOT.fullmatch(slot):
        return lambda: None
    folder = Path(root) / 'shared-runtime' / 'service-health'
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        logging.getLogger(__name__).warning('Could not create independent service health directory.')
        return lambda: None
    path = folder / (slot + '.json')
    stopped = threading.Event()
    opener = build_opener(ProxyHandler({}))

    def write(status, detail, evidence=None,dependencies=None):
        value = dict(id=slot, pid=os.getpid(), updated_at=time.time(), status=status, detail=detail,
                     evidence=safe_evidence(evidence),dependencies=dependency_reports(dependencies))
        temporary = path.with_suffix(f'.{os.getpid()}.tmp')
        try:
            temporary.write_text(json.dumps(value), encoding='utf-8')
            temporary.chmod(0o600)
            temporary.replace(path)
        except OSError:
            pass

    def watch():
        while not stopped.is_set():
            started = time.monotonic()
            evidence = dict(checked_at=time.time(), scope='worker_http')
            dependencies={}
            status, detail = 'unknown', 'Process is starting.'
            if server.should_exit:
                status, detail = 'unavailable', 'Process is draining or shutting down.'
            elif server.started:
                endpoint = '/_internal/availability' if slot.startswith('shared-api-') else '/_internal/ready'
                request = Request(f'http://127.0.0.1:{server.config.port}{endpoint}',
                                  headers={'x-offerpath-worker':os.environ['OFFERPATH_WORKER_TOKEN']})
                try:
                    with opener.open(request, timeout=2) as response:
                        if response.status == 200:
                            raw = response.read(8193)
                            value = json.loads(raw) if isinstance(raw, bytes) and len(raw)<=8192 else None
                            if not isinstance(value,dict) or value.get('ready') is not True:
                                raise ValueError('Invalid health response')
                            status = value.get('status','healthy')
                            if status not in ('healthy','degraded','unknown','unavailable'):
                                raise ValueError('Invalid health status')
                            evidence.update(safe_evidence(value))
                            dependencies=dependency_reports(value.get('dependencies'))
                            evidence['http_status'] = 200
                            detail = 'Direct worker check: '+str(evidence.get('reason','HTTP responsive')).replace('_',' ')+'.'
                except Exception as exc:
                    evidence.update(failure(exc.reason if isinstance(exc,URLError) and isinstance(exc.reason,Exception) else exc))
                    if isinstance(exc,ValueError):
                        evidence['reason'] = 'invalid_health_response'
                    if isinstance(exc,HTTPError):
                        evidence.update(http_status=exc.code, reason=f'http_{exc.code}')
                        try:
                            raw = exc.read(8193)
                            if len(raw)<=8192:
                                evidence.update(safe_evidence(json.loads(raw)))
                        except (OSError,ValueError,TypeError):
                            pass
                        finally:
                            exc.close()
                    status, detail = 'unavailable', 'Direct worker HTTP/runtime check failed. Inspect this worker log.'
            evidence['duration_ms'] = round((time.monotonic()-started)*1000,1)
            write(status, detail, evidence,dependencies)
            stopped.wait(5)

    thread = threading.Thread(target=watch, daemon=True, name='service-health-reporter')
    thread.start()

    def cleanup():
        stopped.set()
        thread.join(timeout=3)
        write('unavailable', 'Process stopped.')
    return cleanup


def read_services(root):
    from .monitoring import process_running
    result = {}
    folder = Path(root) / 'shared-runtime' / 'service-health'
    try:
        paths = list(folder.glob('*.json'))[:128]
    except OSError:
        return result
    for path in paths:
        if not SLOT.fullmatch(path.stem):
            continue
        try:
            with path.open('rb') as stream:
                raw = stream.read(4097)
            value = json.loads(raw) if len(raw) <= 4096 else None
            if not isinstance(value, dict) or value.get('id') != path.stem:
                continue
            pid, at = value.get('pid'), value.get('updated_at')
            if type(pid) is not int or pid <= 0 or type(at) not in (int, float) or not math.isfinite(at):
                continue
            status = value.get('status')
            if status not in ('healthy', 'degraded', 'unknown', 'unavailable'):
                continue
            detail = str(value.get('detail', ''))[:250]
            evidence = safe_evidence(value.get('evidence'))
            try:
                running = process_running(pid)
            except ProcessLookupError:
                running = False
            except OSError:
                running = None
            if running is False:
                status, detail = 'unavailable', f'Process {pid} is no longer running. Inspect {path.stem}.log.'
                evidence['reason'] = 'process_exited'
            elif not 0 <= time.time() - at <= 20:
                status, detail = 'unavailable', f'Process {pid} stopped reporting health. Inspect {path.stem}.log.'
                evidence['reason'] = 'heartbeat_expired'
            result[path.stem] = dict(id=path.stem, name=path.stem, status=status, detail=detail,
                                    **{**evidence,'pid':pid,'checked_at':evidence.get('checked_at',at)})
            for key,item in dependency_reports(value.get('dependencies')).items():
                stale=status=='unavailable'
                result[key+':'+path.stem]={**item,'id':key+':'+path.stem,'name':DEPENDENCIES[key],
                    'detail':'Dependent background task; mail/calendar polling is checked separately.',
                    'pid':pid,'checked_at':evidence.get('checked_at',at)}
                if stale:result[key+':'+path.stem].update(status='unavailable',reason=evidence.get('reason','parent_unavailable'))
        except (OSError, ValueError, TypeError):
            continue
    return result
