"""A busy gateway must not look like a dead gateway to healthy workers."""
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from mailcheck import workspace_workers


class StopWatch(BaseException):
    pass


def run_watch(monkeypatch, outcomes):
    monkeypatch.setenv('OFFERPATH_WORKER_TOKEN', 'worker-secret')
    monkeypatch.setenv('OFFERPATH_GATEWAY_URL', 'http://127.0.0.1:52400')
    monkeypatch.setenv('OFFERPATH_WORKER_LOCK', '/tmp/unused-worker.lock')
    monkeypatch.setattr('sys.argv', ['workspace_workers', '--port', '52401'])
    with patch('mailcheck.maintenance.MaintenanceLock'), \
            patch.object(workspace_workers, 'InstanceLock'), \
            patch('mailcheck.web.app.create_app'), \
            patch('mailcheck.web.server.run'), \
            patch.object(workspace_workers.threading, 'Thread') as thread:
        workspace_workers.main()
        watch = thread.call_args.kwargs['target']
    opener = MagicMock()
    opener.open.side_effect = outcomes
    with patch('urllib.request.build_opener', return_value=opener), \
            patch.object(workspace_workers.time, 'sleep', side_effect=[None] * len(outcomes) + [StopWatch()]), \
            patch.object(workspace_workers.os, '_exit', side_effect=SystemExit(1)):
        watch()


def test_gateway_overload_does_not_kill_worker(monkeypatch):
    overloaded = HTTPError('http://gateway', 503, 'Service Unavailable', {}, None)
    with pytest.raises(StopWatch):
        run_watch(monkeypatch, [overloaded] * 4)


@pytest.mark.parametrize('failure', [
    URLError('Connection refused'),
    HTTPError('http://gateway', 401, 'Unauthorized', {}, None),
    HTTPError('http://gateway', 403, 'Forbidden', {}, None),
])
def test_dead_or_replaced_gateway_still_stops_worker(monkeypatch, failure):
    with pytest.raises(SystemExit, match='1'):
        run_watch(monkeypatch, [failure] * 3)


def test_overload_resets_prior_connection_failures(monkeypatch):
    disconnected = URLError('Connection refused')
    overloaded = HTTPError('http://gateway', 503, 'Service Unavailable', {}, None)
    with pytest.raises(StopWatch):
        run_watch(monkeypatch, [disconnected, disconnected, overloaded, disconnected, disconnected])


def test_gateway_disappearance_after_overload_still_stops_worker(monkeypatch):
    disconnected = URLError('Connection refused')
    overloaded = HTTPError('http://gateway', 503, 'Service Unavailable', {}, None)
    with pytest.raises(SystemExit, match='1'):
        run_watch(monkeypatch, [overloaded, overloaded, disconnected, disconnected, disconnected])
