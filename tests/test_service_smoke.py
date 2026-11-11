import importlib
import pytest


def fetch(path):
    if path=='/platform/live':return 204,{}
    if path=='/api/bootstrap':return 503,{'code':'migration_not_ready','business_ready':False}
    role='core' if '/core/' in path else 'mail' if '/mail/' in path else 'intelligence'
    return 200,{'service':role,'phase':'foundation','business_ready':False,'infrastructure_ready':True}


def test_smoke_accepts_foundation_but_never_certifies_business_readiness():
    module=importlib.import_module('mailcheck.services.verify_stack')
    report=module.check_stack('http://127.0.0.1:52500',fetch=fetch)
    assert report['infrastructure_ready'] is True
    assert report['business_ready'] is False


@pytest.mark.parametrize('bad_path',['/platform/mail/dependencies','/api/bootstrap'])
def test_smoke_rejects_healthy_looking_wrong_or_incomplete_routes(bad_path):
    module=importlib.import_module('mailcheck.services.verify_stack')
    def wrong(path):return (200,{'business_ready':True}) if path==bad_path else fetch(path)
    with pytest.raises(module.VerificationFailed):module.check_stack('http://127.0.0.1:52500',fetch=wrong)


def test_smoke_does_not_contact_a_remote_or_legacy_origin():
    module=importlib.import_module('mailcheck.services.verify_stack')
    for url in ['https://app.offerpath.bid','http://127.0.0.1:52400','http://user:secret@localhost:52500']:
        with pytest.raises(ValueError):module.check_stack(url,fetch=lambda _:pytest.fail('Unsafe target contacted'))
