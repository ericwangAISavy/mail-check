import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.skipif(not shutil.which('docker'),reason='Docker Compose CLI unavailable')
def test_compose_exposes_only_loopback_edge_and_isolates_runtime_secrets(tmp_path):
    from mailcheck.services.bootstrap import initialize
    state=tmp_path/'state';initialize(state)
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['docker','compose','-f',str(root/'deployment/microservices/compose.yaml'),'config','--format','json'],env={**os.environ,'OFFERPATH_SERVICE_STATE_DIR':str(state)},capture_output=True,text=True,check=True)
    config=json.loads(result.stdout)
    assert {name for name,value in config['services'].items() if value.get('ports')}=={'edge'}
    assert config['services']['edge']['ports'][0]['host_ip']=='127.0.0.1'
    assert 'ingress' in config['services']['edge']['networks']
    assert config['networks']['ingress'].get('internal',False) is False
    assert config['networks']['data']['internal'] is True
    for role in ['core','mail','intelligence']:
        service=config['services'][role]
        sources={item['source'] for item in service['secrets']}
        assert sources=={f'{role}_db_password',f'{role}_broker_password'}
        assert service['read_only'] is True
        assert len(service['tmpfs'])==1 and service['tmpfs'][0].startswith('/tmp:')
        assert 'data' not in config['services']['edge']['networks']
        assert int(service['mem_limit'])>0
        assert not any(key.endswith('PASSWORD') for key in service.get('environment',{}))
