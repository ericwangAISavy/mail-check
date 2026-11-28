"""Bounded public shell/asset transport checks, independent of gateway health."""
import hashlib
import gzip
import io
from http.client import IncompleteRead
import re
import time
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..shared.health_evidence import failure


def _fetch(url):
    try:
        with urlopen(Request(url, headers={'User-Agent':'OfferPath-Monitor/1','Accept-Encoding':'gzip'}), timeout=5) as response:
            try:
                body = response.read(4*1024*1024+1)
            except (OSError,TimeoutError,IncompleteRead) as exc:
                exc.health_evidence={'http_status':response.status,'operation':'read_body'}
                if isinstance(exc,IncompleteRead):exc.health_evidence['reason']='response_incomplete'
                raise
            if len(body)>4*1024*1024:
                raise ValueError('Probe response too large')
            if response.headers.get('Content-Encoding','').lower()=='gzip':
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                        body=stream.read(4*1024*1024+1)
                except (gzip.BadGzipFile,EOFError,zlib.error):
                    error=ValueError('Invalid compressed probe response')
                    error.health_evidence={'reason':'invalid_content_encoding','operation':'decompress_body','http_status':response.status}
                    raise error from None
                if len(body)>4*1024*1024:raise ValueError('Decompressed probe response too large')
            return response.status, response.headers.get('Content-Type',''), body
    except HTTPError as exc:
        exc.close()
        return exc.code, '', b''


def _snapshot_once(url, frontend_dir, fetch):
    started = time.monotonic()
    result = dict(id='public-site',name='Public site',status='unknown',scope='public_shell_assets',
                  checked_at=time.time(), reason='not_configured', detail='Public URL is not configured. Browser and authenticated journeys are not tested.')
    if not url:
        return result
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid public origin')
        origin = f'{parsed.scheme}://{parsed.netloc}'
        result['probe_stage']='shell'
        code, content_type, body = fetch(origin+'/login')
        result['http_status'] = code
        result['shell_http_status']=code
        if code != 200:
            result.update(status='unknown' if code in (401,403,429) else 'unavailable',reason=f'http_{code}',
                          detail='Public shell probe did not succeed. Access restrictions and tunnel failures must be checked separately.')
            return result
        html = body.decode('utf-8')
        if 'html' not in content_type or not re.search(r'<div\b[^>]*\bid=["\']root["\']',html):
            result.update(status='unavailable',reason='invalid_app_shell',detail='Public response is not the OfferPath app shell.')
            return result
        scripts = re.findall(r'<script\b[^>]*\bsrc=["\'](/assets/[A-Za-z0-9_.-]+\.js)["\']',html)
        entries = [src for src in scripts if src.rsplit('/',1)[-1].startswith('index-')]
        if not entries:
            result.update(status='unavailable',reason='entry_asset_missing',detail='App shell contains no frontend entry module.')
            return result
        asset = entries[0]
        result['probe_stage']='entry_asset'
        result.pop('http_status',None)
        code, content_type, body = fetch(origin+asset)
        result['http_status'] = code
        result['asset_http_status']=code
        if code != 200:
            result.update(status='unknown' if code in (401,403,429) else 'unavailable',reason=f'http_{code}',detail='Public entry-module request failed.')
        elif 'javascript' not in content_type:
            result.update(status='unavailable',reason='asset_content_mismatch',detail='Public entry-module response is not JavaScript.')
        else:
            local = frontend_dir/asset.lstrip('/')
            if not local.is_file():
                result.update(reason='deployment_mismatch',detail='Public entry module is not present in this installation. Verify which server is deployed.')
            elif hashlib.sha256(body).digest() != hashlib.sha256(local.read_bytes()).digest():
                result.update(status='unavailable',reason='asset_content_mismatch',detail='Public JavaScript bytes differ from the installed build. Check proxy/cache or incomplete deployment.')
            else:
                result.update(status='healthy',reason='shell_and_entry_verified',detail='Public shell and entry-module bytes verified. Browser execution, lazy modules, and authenticated journeys are not tested.')
    except Exception as exc:
        actual = exc.reason if isinstance(exc,URLError) and isinstance(exc.reason,Exception) else exc
        result.update(status='unavailable',detail=f"Public {result.get('probe_stage','configuration')} probe failed.",**failure(actual))
    finally:
        result['duration_ms'] = round((time.monotonic()-started)*1000,1)
    return result


def public_snapshot(url, frontend_dir, *, fetch=_fetch):
    started=time.monotonic()
    result=_snapshot_once(url,frontend_dir,fetch)
    result['attempts']=1
    if result['status']=='unavailable' and result['reason'] in {
            'timeout','response_incomplete','connection_refused','connection_error','dns_error','os_error','http_502','http_503','http_504'}:
        initial=result
        result=_snapshot_once(url,frontend_dir,fetch)
        result.update(attempts=2,first_failure_reason=initial['reason'],first_failure_stage=initial.get('probe_stage','shell'),
                      recovered_after_retry=result['status']=='healthy')
    result['duration_ms']=round((time.monotonic()-started)*1000,1)
    return result
