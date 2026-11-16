import threading
from types import SimpleNamespace
import pytest
from mailcheck.workspaces import WorkspaceContext, bind_workspace, bind_commit_guard


def test_shutdown_aborts_joins_and_rejects_late_persistence(tmp_path):
    from mailcheck.shared.auth_flows import SharedAuthFlows
    release = threading.Event()
    writes = []
    pending = SimpleNamespace()
    flows = SharedAuthFlows(lambda flow: release.set())
    context = WorkspaceContext('legacy', None, tmp_path/'c', tmp_path/'d', tmp_path)
    def work():
        release.wait(2)
        try:
            with flows.persistence(pending):
                writes.append('token')
        except RuntimeError:
            pass
    with bind_workspace(context):
        thread = flows.start(pending, work)
    flows.stop()
    assert not thread.is_alive()
    assert writes == []
    with bind_workspace(context), pytest.raises(RuntimeError):
        flows.start(SimpleNamespace(), lambda: None)


def test_flow_preserves_context_and_revalidates_before_writes(tmp_path):
    from mailcheck.shared.auth_flows import SharedAuthFlows
    from mailcheck.workspaces import current_workspace
    release = threading.Event()
    writes = []
    checked = []
    pending = SimpleNamespace()
    flows = SharedAuthFlows(lambda flow: release.set())
    context = WorkspaceContext('legacy', None, tmp_path/'c', tmp_path/'d', tmp_path)
    def denied():
        checked.append(current_workspace())
        raise ValueError('disabled')
    def work():
        release.wait(2)
        try:
            with flows.persistence(pending):
                writes.append('token')
        except ValueError:
            pass
    with bind_workspace(context), bind_commit_guard(denied):
        thread = flows.start(pending, work)
    release.set()
    thread.join(2)
    assert checked == [context]
    assert writes == []
    flows.stop()


@pytest.mark.parametrize('shutdown', [True, False])
def test_shared_app_device_flow_cannot_persist_after_shutdown_or_disable(tmp_path, monkeypatch, shutdown):
    import asyncio
    from contextlib import contextmanager
    from unittest.mock import Mock
    from mailcheck.web import app as module
    release = threading.Event()
    allowed = [True]
    writes = []
    pending = SimpleNamespace(id='fixture', completed_cache='token', user_code='123', verification_uri='url')
    @contextmanager
    def session():
        yield Mock()
    def complete(flow):
        release.wait(3)
        return 'fixture@example.org'
    def guard():
        if not allowed[0]:
            raise ValueError('disabled')
    monkeypatch.setattr(module.cfgmod, 'load', lambda: SimpleNamespace(outlook=SimpleNamespace(client_id='fixture')))
    monkeypatch.setattr(module.db, 'session', session)
    monkeypatch.setattr(module.db, 'get_account', lambda *args: None)
    monkeypatch.setattr(module.db, 'add_account', lambda *args, **kwargs: writes.append('account'))
    monkeypatch.setattr(module.outlook_auth, 'begin_device_flow', lambda *args: pending)
    monkeypatch.setattr(module.outlook_auth, 'complete_device_flow', complete)
    monkeypatch.setattr(module.outlook_auth, 'save_cache', lambda *args: writes.append('cache'))
    monkeypatch.setattr(module.outlook_auth, 'abort', lambda flow: release.set())
    # All app and thread state belongs to this temporary context.
    context = WorkspaceContext('legacy', None, tmp_path/'c', tmp_path/'d', tmp_path)
    with bind_workspace(context), bind_commit_guard(guard):
        app = module.create_app.__wrapped__(worker_secret='fixture', shared=True)
        endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/outlook/start')
        assert endpoint(module.OutlookStartBody(label='fixture'))['ok']
        async def lifespan():
            async with app.router.lifespan_context(app):
                if not shutdown:
                    allowed[0] = False
                    release.set()
                    # The lifespan's drain joins the thread before assertions.
        asyncio.run(lifespan())
    assert writes == []


def test_pending_workspace_capacity_and_successful_persistence(tmp_path):
    from mailcheck.shared.auth_flows import SharedAuthFlows
    release = threading.Event()
    writes = []
    flows = SharedAuthFlows(lambda flow: release.set(), capacity=1)
    context = WorkspaceContext('legacy', None, tmp_path/'c', tmp_path/'d', tmp_path)
    first = SimpleNamespace()
    def work():
        release.wait(3)
    with bind_workspace(context):
        thread = flows.start(first, work)
        with flows.persistence(first):
            writes.append('allowed')
    other = WorkspaceContext('other', None, tmp_path/'c', tmp_path/'d', tmp_path)
    with bind_workspace(other), pytest.raises(RuntimeError, match='Too many'):
        flows.start(SimpleNamespace(), lambda: None)
    flows.stop()
    assert writes == ['allowed']
    assert not thread.is_alive()
