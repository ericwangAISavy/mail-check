import gzip
import io
from http.client import IncompleteRead
import pytest

from mailcheck.web import public_health


HTML=b'<div id="root"></div><script type="module" src="/assets/index-test.js"></script>'
JS=b'export const ready=true;'


def installation(tmp_path):
    (tmp_path/'assets').mkdir()
    (tmp_path/'assets'/'index-test.js').write_bytes(JS)
    return tmp_path


def test_asset_timeout_does_not_reuse_shell_status_and_retries_once(tmp_path):
    calls=[]
    def fetch(url):
        calls.append(url)
        if url.endswith('/login'):return 200,'text/html',HTML
        raise TimeoutError('private response content')
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['status']=='unavailable'
    assert result['probe_stage']=='entry_asset'
    assert 'http_status' not in result
    assert result['shell_http_status']==200
    assert result['attempts']==2 and len(calls)==4
    assert 'private' not in str(result)


def test_one_transient_timeout_can_recover_with_verified_asset_bytes(tmp_path):
    calls=[]
    def fetch(url):
        calls.append(url)
        if len(calls)==1:raise TimeoutError()
        return (200,'text/html',HTML) if url.endswith('/login') else (200,'text/javascript',JS)
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['status']=='healthy' and result['attempts']==2
    assert result['recovered_after_retry'] is True
    assert result['first_failure_reason']=='timeout'


def test_content_corruption_is_not_retried(tmp_path):
    calls=[]
    def fetch(url):
        calls.append(url)
        return (200,'text/html',HTML) if url.endswith('/login') else (200,'text/javascript',b'corrupt')
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['reason']=='asset_content_mismatch' and len(calls)==2
    assert result['attempts']==1


def test_fetch_requests_compression_and_verifies_decompressed_bytes(monkeypatch):
    response=io.BytesIO(gzip.compress(JS))
    response.status=200
    response.headers={'Content-Type':'text/javascript','Content-Encoding':'gzip'}
    def open_response(request,timeout):
        assert request.get_header('Accept-encoding')=='gzip'
        assert timeout==5
        return response
    monkeypatch.setattr(public_health,'urlopen',open_response)
    assert public_health._fetch('https://example.test/asset')==(200,'text/javascript',JS)


def test_compressed_response_keeps_the_decompressed_size_limit(monkeypatch):
    response=io.BytesIO(gzip.compress(b'x'*(4*1024*1024+1)))
    response.status=200;response.headers={'Content-Encoding':'gzip'}
    monkeypatch.setattr(public_health,'urlopen',lambda *args,**kwargs:response)
    with pytest.raises(ValueError,match='Decompressed probe response too large'):
        public_health._fetch('https://example.test/asset')


def test_body_timeout_identifies_the_request_stage_and_real_headers(tmp_path,monkeypatch):
    class Response(io.BytesIO):
        status=200
        headers={'Content-Type':'text/javascript'}
        def read(self,*args):raise TimeoutError('private body text')
    monkeypatch.setattr(public_health,'urlopen',lambda *args,**kwargs:Response())
    def fetch(url):
        return (200,'text/html',HTML) if url.endswith('/login') else public_health._fetch(url)
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['probe_stage']=='entry_asset'
    assert result['operation']=='read_body'
    assert result['http_status']==200  # Real entry headers, rather than the preceding shell status.
    assert result['attempts']==2 and result['status']=='unavailable'
    assert 'private' not in str(result)


def test_incomplete_asset_body_is_retried_with_body_evidence(tmp_path,monkeypatch):
    class Response(io.BytesIO):
        status=200
        headers={'Content-Type':'text/javascript'}
        def read(self,*args):raise IncompleteRead(b'private partial bytes')
    monkeypatch.setattr(public_health,'urlopen',lambda *args,**kwargs:Response())
    def fetch(url):
        return (200,'text/html',HTML) if url.endswith('/login') else public_health._fetch(url)
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['reason']=='response_incomplete' and result['attempts']==2
    assert result['operation']=='read_body' and result['http_status']==200
    assert 'private' not in str(result)


def test_invalid_gzip_is_a_content_failure_without_retry(tmp_path,monkeypatch):
    calls=[]
    def open_response(*args,**kwargs):
        calls.append(1)
        response=io.BytesIO(b'not compressed')
        response.status=200;response.headers={'Content-Encoding':'gzip'}
        return response
    monkeypatch.setattr(public_health,'urlopen',open_response)
    def fetch(url):
        return (200,'text/html',HTML) if url.endswith('/login') else public_health._fetch(url)
    result=public_health.public_snapshot('https://example.test',installation(tmp_path),fetch=fetch)
    assert result['attempts']==1 and len(calls)==1
    assert result['reason']=='invalid_content_encoding'
