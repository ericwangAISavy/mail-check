import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from mailcheck.web.local_monitor import Observer, create_app
from mailcheck.web.server import LocalOriginHealth
from mailcheck.web.admission import RequestAdmission


def test_launcher_replaces_legacy_monitor_instead_of_reusing_its_health_endpoint(tmp_path):
    from mailcheck.web import local_monitor
    def connection(value):
        client = Mock()
        if value is None:
            client.request.side_effect = ConnectionRefusedError()
        else:
            client.getresponse.return_value.status = 200
            client.getresponse.return_value.read.return_value = json.dumps(value).encode()
        return client
    old = {'service':'offerpath-local-monitor'}
    current = {**old, 'version':local_monitor.__version__}
    with patch.object(local_monitor.sys, 'argv', ['monitor', '--ensure']), patch.object(
        local_monitor, 'HTTPConnection', side_effect=[connection(old), connection(None), connection(current)]
    ), patch.object(local_monitor, 'stop_existing_monitor') as stop, patch.object(
        local_monitor.config, 'control_dir', return_value=tmp_path
    ), patch.object(local_monitor.subprocess, 'Popen') as spawn:
        assert local_monitor.main() is None
        stop.assert_called_once_with(52401)
        spawn.assert_called_once()


def test_independent_console_keeps_last_snapshot_and_logs_during_origin_outage(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'origin-supervisor.log').write_text('Restarting after a failure', encoding='utf-8')
    observer = Observer(tmp_path, 52400)
    with patch('mailcheck.web.local_monitor.origin_state', return_value='ready'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', return_value={'checked_at': 1, 'components': []}
    ):
        observer.sample()
    with patch('mailcheck.web.local_monitor.origin_state', return_value='unavailable'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError('origin down')
    ):
        observer.sample()
    assert observer.status()['origin'] == 'unavailable'
    assert next(c for c in observer.status()['snapshot']['components'] if c['id']=='gateway')['status'] == 'unavailable'
    assert not observer.status()['snapshot_stale']
    assert observer.status()['outage_since'] is not None
    outage_since = observer.status()['outage_since']
    with patch('mailcheck.web.local_monitor.origin_state', return_value='unavailable'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError('origin down')
    ):
        observer.sample()
    assert observer.status()['outage_since'] == outage_since
    with patch('mailcheck.web.local_monitor.origin_state', return_value='ready'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError('snapshot unavailable')
    ):
        observer.sample()
    assert observer.status()['outage_since'] is None
    assert 'Restarting' in observer.log_tail('origin-supervisor.log')


def test_broken_http_snapshot_does_not_leave_origin_reported_as_ready(tmp_path):
    from http.client import BadStatusLine
    observer = Observer(tmp_path, 52400)
    observer.state = 'ready'
    with patch('mailcheck.web.local_monitor.origin_state', return_value='unavailable'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', side_effect=BadStatusLine('broken response')
    ):
        observer.sample()
    assert observer.status()['origin'] == 'unavailable'


def test_unreadable_log_returns_actionable_error(tmp_path):
    import pytest
    from fastapi import HTTPException
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'origin-server.log').write_text('error', encoding='utf-8')
    observer = Observer(tmp_path, 52400)
    with patch('pathlib.Path.open', side_effect=PermissionError('denied')):
        with pytest.raises(HTTPException) as error:
            observer.log_tail('origin-server.log')
    assert error.value.status_code == 503


def test_launcher_does_not_spawn_when_old_monitor_never_stops(tmp_path):
    from mailcheck.web import local_monitor
    client = Mock()
    client.getresponse.return_value.status = 200
    client.getresponse.return_value.read.return_value = b'{"service":"offerpath-local-monitor"}'
    with patch.object(local_monitor.sys, 'argv', ['monitor','--ensure']), patch.object(
        local_monitor, 'HTTPConnection', return_value=client
    ), patch.object(local_monitor, 'stop_existing_monitor'), patch.object(
        local_monitor.time, 'sleep'
    ), patch.object(local_monitor.subprocess, 'Popen') as spawn:
        assert local_monitor.main() == 1
        spawn.assert_not_called()


def test_monitor_serves_without_origin_and_rejects_foreign_host(tmp_path):
    async def scenario():
        app = create_app(tmp_path)
        app.state.observer.latest = {'checked_at':1,'components':[],'workspaces':[],'events':[]}
        app.state.observer.metrics['1h'] = {'range':'1h','buckets':[1], 'summary':{'requests':12}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:52401') as client:
            page = await client.get('/')
            assert page.status_code == 200
            assert 'data-local-monitor="true"' in page.text
            assert (await client.get('/api/status')).status_code == 200
            snapshot = await client.get('/api/admin/system-monitoring')
            assert snapshot.json()['checked_at'] == 1
            metrics = await client.get('/api/admin/system-monitoring/metrics?range=1h')
            assert metrics.json()['summary']['requests'] == 12
            assert (await client.get('/api/admin/system-monitoring/metrics?range=bad')).status_code == 422
            assert (await client.get('/api/status', headers={'host':'attacker.example'})).status_code == 403
            assert (await client.get('/api/log', params={'name':'../secrets.log'})).status_code == 404
    asyncio.run(scenario())


def test_origin_probe_detects_failed_application_behind_live_http_listener():
    async def unhealthy():
        return False
    async def app(scope, receive, send):
        raise AssertionError('Should use the application health callback')
    app.state = SimpleNamespace(origin_health=unhealthy)
    async def scenario():
        wrapped = LocalOriginHealth(RequestAdmission(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped, client=('127.0.0.1', 1234)),
                                     base_url='http://127.0.0.1') as client:
            response = await client.get('/_internal/origin-health')
            assert response.status_code == 503
            assert response.headers['x-offerpath-health'] == '0'
    asyncio.run(scenario())


def test_monitor_process_survives_origin_disappearing(tmp_path):
    import json
    import socket
    import subprocess
    import sys
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import build_opener, ProxyHandler

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith('origin-health'):
                self.send_response(204)
                self.send_header('X-OfferPath-Health', '1')
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'checked_at':time.time(), 'components':[]}).encode())

        def log_message(self, *args):
            pass

    origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    thread = threading.Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    script = ('from pathlib import Path; import sys; from mailcheck.web.local_monitor import create_app; '
              'from mailcheck.web.server import run; '
              'run(create_app(Path(sys.argv[1]),int(sys.argv[3])),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")')
    process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path), str(port), str(origin.server_port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    opener = build_opener(ProxyHandler({}))
    def wait_for(state):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert process.poll() is None
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/status', timeout=1) as response:
                    value = json.load(response)
                if value['origin'] == state:
                    return value
            except OSError:
                pass
            time.sleep(.2)
        raise AssertionError(f'Monitor did not report {state}')
    try:
        wait_for('ready')
        origin.shutdown()
        origin.server_close()
        value = wait_for('unavailable')
        assert value['snapshot'] is not None
        assert not value['snapshot_stale']
        assert process.poll() is None
    finally:
        origin.shutdown()
        origin.server_close()
        process.terminate()
        process.wait(timeout=10)
