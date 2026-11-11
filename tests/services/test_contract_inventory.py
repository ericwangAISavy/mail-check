"""Source inventory prevents business routes and persisted tables being missed."""
import json
from pathlib import Path


def test_inventory_discovers_routes_and_tables_without_importing_application(tmp_path):
    from tools.service_migration_inventory import inventory
    web=tmp_path/'mailcheck/web';web.mkdir(parents=True)
    (web/'app.py').write_text('raise RuntimeError("must not execute source")\n@app.post("/api/items")\ndef add(): pass\n')
    (tmp_path/'mailcheck/db.py').write_text('SCHEMA="CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY);"\n')
    report=inventory(tmp_path)
    assert report['routes']==[{'source':'mailcheck/web/app.py','handler':'add','path':'/api/items','methods':['POST']}]
    assert report['tables']==[{'name':'items','sources':['mailcheck/db.py']}]


def test_every_discovered_legacy_contract_has_an_explicit_migration_disposition():
    from tools.service_migration_inventory import inventory
    root=Path(__file__).resolve().parents[2]
    discovered=inventory(root)
    declared=json.loads((root/'docs/architecture/MIGRATION_CONTRACTS.json').read_text())
    assert [{key:row[key] for key in ('source','handler','path','methods')} for row in declared['routes']]==discovered['routes']
    assert [{key:row[key] for key in ('name','sources')} for row in declared['tables']]==discovered['tables']
    assert all(row['owner'] in {'core','mail','intelligence','edge'} and row['status'] in {'pending','implemented','verified'} for row in declared['routes'])
    assert all(row['owner'] in {'core','mail','intelligence'} and row['disposition'] in {'preserve','invalidate_sessions','archive_deprecated'} for row in declared['tables'])
    assert declared['manual_registration_review']==discovered['manual_registration_review']
    assert declared['business_ready'] is False
