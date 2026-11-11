import importlib
import json
from pathlib import Path
import pytest


def test_initialization_is_private_and_preserves_existing_credentials(tmp_path):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'stack'
    assert module.initialize(root)=='created'
    before={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}
    assert module.initialize(root)=='existing'
    assert before=={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}
    assert len(before)==11
    assert (root.stat().st_mode & 0o077)==0
    assert (root/'secrets/core_db_password').stat().st_mode & 0o077==0
    definitions=json.loads((root/'secrets/rabbitmq_definitions').read_text())
    assert all('password' not in user for user in definitions['users'])


def test_partial_directory_is_not_silently_reinitialized(tmp_path):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'stack';root.mkdir();(root/'important').write_text('retain')
    with pytest.raises(ValueError):module.initialize(root)
    assert (root/'important').read_text()=='retain'


def test_changed_or_symlinked_credentials_are_rejected(tmp_path):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'stack';module.initialize(root)
    (root/'secrets/core_broker_password').write_text('y'*43)
    with pytest.raises(ValueError):module.initialize(root)
    other=tmp_path/'other';other.symlink_to(root,target_is_directory=True)
    with pytest.raises(ValueError):module.initialize(other)


def test_preflight_never_claims_unmeasured_capacity_or_cold_boot_is_verified():
    module=importlib.import_module('mailcheck.services.preflight')
    report=module.preflight(run=lambda *_:None,model_url=None)
    assert report['migration_ready'] is False
    assert report['gates']['cold_boot']=='not_verified'
    assert report['gates']['model_peak_memory']=='not_measured'
    assert 'password' not in json.dumps(report).lower()


def test_outdated_topology_requires_an_explicit_upgrade(tmp_path,monkeypatch):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'stack';module.initialize(root)
    monkeypatch.setattr(module,'TOPOLOGY_VERSION',999)
    with pytest.raises(ValueError):module.initialize(root)
