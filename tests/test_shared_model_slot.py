from pathlib import Path
import pytest

from mailcheck.llm.workspace_queue import shared_model_slot
from mailcheck.shared.state import OperationLock
from mailcheck.workspaces import WorkspaceContext,bind_workspace


def test_shared_model_admission_is_independent_of_gateway_during_drain(tmp_path,monkeypatch):
    context=WorkspaceContext.from_record({'id':'legacy','root':None},(tmp_path/'c',tmp_path/'d'),tmp_path/'control')
    monkeypatch.setenv('OFFERPATH_GATEWAY_URL','http://unavailable.invalid')
    monkeypatch.setenv('OFFERPATH_WORKER_TOKEN','private')
    @shared_model_slot
    def operation():
        probe=OperationLock(context.control_root/'shared-runtime'/'model.lock')
        assert not probe.acquire(False)
        return 'completed'
    with bind_workspace(context):
        assert operation()=='completed'
    probe=OperationLock(context.control_root/'shared-runtime'/'model.lock')
    assert probe.acquire(False)
    probe.release()
