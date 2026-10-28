import pytest
from mailcheck.workspace_workers import gateway_address

@pytest.mark.parametrize('host,expected',[
    ('0.0.0.0','http://127.0.0.1:52400'),
    ('127.0.0.2','http://127.0.0.2:52400'),
    ('192.168.1.76','http://192.168.1.76:52400'),
    ('::','http://[::1]:52400'),
    ('::1','http://[::1]:52400'),
])
def test_internal_gateway_address_follows_actual_bind(host,expected):
    assert gateway_address(host,52400)==expected


def test_specific_bind_keeps_the_original_worker_alive_past_heartbeat_deadline(tmp_path):
    import os,socket,subprocess,sys,time
    from pathlib import Path
    import httpx
    from mailcheck.web.auth import AuthStore
    root=tmp_path/'original';root.mkdir()
    config_file=root/'config.toml';config_file.write_text('[watch]\nauto_check=false\n')
    AuthStore(lambda:root/'web-auth.json').change_password('admin','owner-password-123')
    with socket.socket() as sock:sock.bind(('127.0.0.2',0));port=sock.getsockname()[1]
    env=os.environ.copy()
    env.update(OFFERPATH_LEGACY_CONFIG_PATH=str(config_file),OFFERPATH_LEGACY_DB_PATH=str(root/'mailcheck.db'))
    process=subprocess.Popen([sys.executable,'-m','mailcheck','web','--no-open','--host','127.0.0.2','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=gateway_address('127.0.0.2',port),trust_env=False,timeout=15) as client:
            for _ in range(100):
                try:
                    if client.get('/api/auth/session').status_code==200:break
                except httpx.HTTPError:time.sleep(.1)
            response=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'})
            assert response.status_code==200,response.text
            client.headers['x-offerpath-workspace']='legacy'
            assert client.get('/api/bootstrap').status_code==200
            original=next(row for row in client.get('/api/admin/users').json()['admins'] if row['owner'])['worker_started_at']
            assert original is not None
            deadline=time.monotonic()+16
            while time.monotonic()<deadline:
                assert process.poll() is None
                time.sleep(.5)
            current=next(row for row in client.get('/api/admin/users').json()['admins'] if row['owner'])
            assert current['worker_started_at']==original, 'The initial worker restarted after failed parent heartbeats.'
            assert current['health']=='running'
            assert client.get('/api/bootstrap').status_code==200
    finally:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
