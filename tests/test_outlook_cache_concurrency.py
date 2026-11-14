import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from mailcheck import outlook_auth as auth


def test_chunked_cache_writers_cannot_interleave(monkeypatch):
    values={}
    paused=threading.Event();release=threading.Event();inside=threading.Event()
    def put(service,key,value):
        if threading.current_thread().name.endswith('_0') and key.endswith(':0'):
            values[key]=value
            inside.set();paused.set()
            assert release.wait(2)
            inside.clear()
        else:
            assert not inside.is_set(), 'Concurrent writers interleaved credential chunks'
            values[key]=value
    monkeypatch.setattr(auth.keyring,'set_password',put)
    monkeypatch.setattr(auth.keyring,'get_password',lambda service,key:values.get(key))
    monkeypatch.setattr(auth.keyring,'delete_password',lambda service,key:values.pop(key,None))
    first='A'*(auth.CHUNK_CHARS*3)
    second='B'*(auth.CHUNK_CHARS*3)
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix='cache') as executor:
        a=executor.submit(auth._write_blob,'concurrency-test',first)
        assert paused.wait(2)
        b=executor.submit(auth._write_blob,'concurrency-test',second)
        try:
            # Give the competing writer a chance to enter while A is paused.
            threading.Event().wait(.05)
        finally:release.set()
        a.result();b.result()
    assert auth._read_blob('concurrency-test')==second


def test_silent_refresh_serializes_the_entire_load_update_save(monkeypatch):
    value={'version':0}
    paused=threading.Event();release=threading.Event()
    def load(label):return SimpleNamespace(version=value['version'])
    def app(client_id,cache):
        def refresh(*args,**kwargs):
            if threading.current_thread().name.endswith('_0'):
                paused.set();assert release.wait(2)
            cache.version+=1
            return {'access_token':'synthetic-token'}
        return SimpleNamespace(get_accounts=lambda:[{}],acquire_token_silent=refresh)
    monkeypatch.setattr(auth,'load_cache',load)
    monkeypatch.setattr(auth,'save_cache',lambda label,cache:value.update(version=cache.version))
    monkeypatch.setattr(auth,'_app',app)
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix='refresh') as executor:
        a=executor.submit(auth.acquire_token,'refresh-test','client')
        assert paused.wait(2)
        b=executor.submit(auth.acquire_token,'refresh-test','client')
        try:threading.Event().wait(.05)
        finally:release.set()
        assert a.result()=='synthetic-token'
        assert b.result()=='synthetic-token'
    assert value['version']==2


def test_cache_lock_coordinates_separate_processes(tmp_path):
    import subprocess
    import sys
    started=tmp_path/'started'
    entered=tmp_path/'entered'
    code='''
import sys
from pathlib import Path
from mailcheck.outlook_auth import _cache_lock
Path(sys.argv[1]).write_text('started')
with _cache_lock('separate-process-test'):
    Path(sys.argv[2]).write_text('entered')
'''
    child=None
    try:
        with auth._cache_lock('separate-process-test'):
            child=subprocess.Popen([sys.executable,'-c',code,str(started),str(entered)])
            for _ in range(100):
                if started.exists():break
                threading.Event().wait(.02)
            assert started.exists()
            threading.Event().wait(.05)
            assert not entered.exists(), 'Another process bypassed the held credential lock'
        assert child.wait(timeout=5)==0
        assert entered.exists()
    finally:
        if child is not None and child.poll() is None:
            child.kill();child.wait()
