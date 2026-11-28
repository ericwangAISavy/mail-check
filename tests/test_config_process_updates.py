import os
import subprocess
import sys
import time

from mailcheck import config


def test_cli_and_web_style_settings_updates_do_not_overwrite_each_other(tmp_path,monkeypatch):
    path=tmp_path/'config.toml'
    monkeypatch.setattr(config,'config_path',lambda:path)
    config.save(config.Config())
    started,done=tmp_path/'started',tmp_path/'done'
    child_env=os.environ.copy()
    child_env['OFFERPATH_LEGACY_CONFIG_PATH']=str(path)
    for name in ('OFFERPATH_SHARED_CONFIG_PATH','OFFERPATH_WORKSPACE_ROOT','OFFERPATH_WORKSPACE_ID'):
        child_env.pop(name,None)
    code='''
import sys
from pathlib import Path
from typer.testing import CliRunner
from mailcheck.cli import app
Path(sys.argv[1]).touch()
result=CliRunner().invoke(app,['config','set','check.retain_days','99'])
if result.exit_code:raise SystemExit(result.exit_code)
Path(sys.argv[2]).touch()
'''
    child=None
    try:
        with config.update_lock():
            settings=config.load()
            child=subprocess.Popen([sys.executable,'-c',code,str(started),str(done)],env=child_env)
            for _ in range(200):
                if started.exists():break
                time.sleep(.01)
            assert started.exists()
            for _ in range(50):
                if done.exists():break
                time.sleep(.01)
            settings.check.lookback_days=9
            config.save(settings)
        assert child.wait(timeout=5)==0
        final=config.load()
        assert final.check.lookback_days==9
        assert final.check.retain_days==99
    finally:
        if child is not None and child.poll() is None:
            child.kill();child.wait()
