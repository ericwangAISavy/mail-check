import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def release_tool():
    spec = importlib.util.spec_from_file_location('offerpath_release', ROOT/'tools'/'release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_metadata_and_generated_history_are_synchronized():
    release_tool().check(ROOT)


@pytest.mark.parametrize('kind', ['patch','minor','major'])
def test_release_bump_updates_all_versions_and_preserves_history(tmp_path, kind):
    for name in ('releases.json','pyproject.toml','mailcheck/__init__.py','frontend/package.json','frontend/package-lock.json','docs/CHANGELOG.md'):
        destination = tmp_path/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, destination)
    tool = release_tool()
    previous = json.loads((tmp_path/'releases.json').read_text())
    major, minor, patch = tool.version_tuple(previous[0]['version'])
    expected = {'patch':f'{major}.{minor}.{patch+1}', 'minor':f'{major}.{minor+1}.0', 'major':f'{major+1}.0.0'}[kind]
    tool.bump(tmp_path, kind, 'Test update', ['A useful change.'], '2026-10-29')
    tool.check(tmp_path)
    history = json.loads((tmp_path/'releases.json').read_text())
    assert history[0]['version'] == expected
    assert history[1:] == previous
    assert 'A useful change.' in (tmp_path/'docs/CHANGELOG.md').read_text()


def test_release_check_detects_stale_generated_history(tmp_path):
    for name in ('releases.json','pyproject.toml','mailcheck/__init__.py','frontend/package.json','frontend/package-lock.json','docs/CHANGELOG.md'):
        destination = tmp_path/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, destination)
    (tmp_path/'docs/CHANGELOG.md').write_text('stale')
    with pytest.raises(ValueError, match='CHANGELOG'):
        release_tool().check(tmp_path)


def test_runtime_changes_require_release_and_published_notes_cannot_be_rewritten(tmp_path):
    import subprocess
    for name in ('releases.json','pyproject.toml','mailcheck/__init__.py','frontend/package.json','frontend/package-lock.json','docs/CHANGELOG.md'):
        destination = tmp_path/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, destination)
    def git(*args):
        subprocess.run(['git',*args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    git('add','.')
    git('-c','user.name=Release test','-c','user.email=release@example.test','commit','-m','Baseline')
    runtime = tmp_path/'mailcheck/__init__.py'
    runtime.write_text(runtime.read_text()+"\ndef added_feature(): return 'new'\n")
    tool = release_tool()
    with pytest.raises(ValueError, match='version bump'):
        tool.check(tmp_path, 'HEAD')
    tool.bump(tmp_path, 'patch', 'A change', ['New feature'], '2026-10-29')
    tool.check(tmp_path, 'HEAD')
    entries = tool.history(tmp_path)
    entries[-1]['changes'].append('Rewrote a published release')
    (tmp_path/'releases.json').write_text(json.dumps(entries))
    (tmp_path/'docs/CHANGELOG.md').write_text(tool.changelog(entries))
    with pytest.raises(ValueError, match='retained unchanged'):
        tool.check(tmp_path, 'HEAD')
