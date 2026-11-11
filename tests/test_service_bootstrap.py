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


def test_empty_state_directory_in_a_path_with_spaces_can_be_initialized(tmp_path):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'smoke Test- mail-check'/'.local'
    root.mkdir(parents=True)
    assert module.initialize(root)=='created'
    before={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}
    assert module.initialize(root)=='existing'
    assert before=={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}


def test_init_reports_missing_manifest_without_exposing_or_overwriting_existing_data(tmp_path,monkeypatch,capsys):
    import sys
    from mailcheck.services import manage
    root=tmp_path/'state';root.mkdir()
    valuable=root/'saved-credential';valuable.write_text('private-secret-must-not-be-printed')
    monkeypatch.setattr(sys,'argv',['manage','init','--state-dir',str(root)])
    assert manage.main()==1
    report=json.loads(capsys.readouterr().out)
    assert report['code']=='state_manifest_missing'
    assert report['hint']
    assert 'private-secret-must-not-be-printed' not in json.dumps(report)
    assert valuable.read_text()=='private-secret-must-not-be-printed'


def test_init_identifies_changed_state_without_rotating_credentials(tmp_path,monkeypatch,capsys):
    import sys
    from mailcheck.services import manage
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'state';module.initialize(root)
    credential=root/'secrets/core_db_password';credential.write_text('z'*43)
    before={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}
    monkeypatch.setattr(sys,'argv',['manage','init','--state-dir',str(root)])
    assert manage.main()==1
    report=json.loads(capsys.readouterr().out)
    assert report['code']=='state_files_changed'
    assert 'z'*43 not in json.dumps(report)
    assert before=={p.name:p.read_bytes() for p in (root/'secrets').iterdir()}


@pytest.mark.parametrize('damage,code',[
    ('manifest','state_manifest_invalid'),
    ('file','state_files_missing'),
    ('path','state_not_directory'),
])
def test_init_diagnostics_distinguish_invalid_state_without_removing_it(tmp_path,damage,code):
    module=importlib.import_module('mailcheck.services.bootstrap')
    root=tmp_path/'state'
    if damage=='path':root.write_text('preserve this file')
    else:
        module.initialize(root)
        if damage=='manifest':(root/'manifest.json').write_text('{broken json')
        else:(root/'secrets/core_db_password').unlink()
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()} if root.is_dir() else root.read_bytes()
    with pytest.raises(module.InitializationError) as error:module.initialize(root)
    assert error.value.code==code
    after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()} if root.is_dir() else root.read_bytes()
    assert before==after
