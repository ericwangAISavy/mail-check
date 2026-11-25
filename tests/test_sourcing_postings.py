import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event,Lock

import httpx
import pytest

from mailcheck import sourcing_postings as postings
from tests.test_sourcing_fallbacks import records


def test_posting_keys_keep_job_identity_and_ignore_tracking():
    a='https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123456&jr_id=tracking'
    b='https://job-boards.greenhouse.io/acme/jobs/123456?utm_source=mail'
    assert postings.posting_key(a)==postings.posting_key(b)
    assert postings.posting_key(a)!=postings.posting_key(b.replace('123456','987654'))
    assert postings.specification('https://company.wd1.myworkdayjobs.com/jobs/job/Engineer_R1608282-1')[-1]=='R1608282'


def test_brassring_identity_ignores_site_and_tracking_but_keeps_employer_and_job():
    url='https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=26224&siteid=5247&PageType=JobDetails&jobid=1442605&jr_id=first'
    variant=url.replace('5247','5251').replace('first','second')
    assert postings.specification(url)==('brassring','26224','1442605')
    assert postings.posting_key(url)==postings.posting_key(variant)
    assert postings.posting_key(url)!=postings.posting_key(url.replace('1442605','1442606'))
    assert postings.posting_key(url)!=postings.posting_key(url.replace('26224','26225'))


@pytest.mark.parametrize('url',[
    'http://job-boards.greenhouse.io/acme/jobs/12345',
    'https://job-boards.greenhouse.io.evil.test/acme/jobs/12345',
    'https://127.0.0.1/private','https://localhost/private',
    'https://user:password@job-boards.greenhouse.io/acme/jobs/12345',
    'https://jobs.ashbyhq.com:52400/acme/efc949ef-22ce-401c-8161-091e387e776d',
])
def test_untrusted_targets_are_never_fetched(monkeypatch,url):
    monkeypatch.setattr(postings,'_download',lambda *_:pytest.fail('Unexpected external request'))
    assert postings.fetch_posting(url) is None


def test_metadata_parsers_use_fixed_endpoints_and_actual_titles(monkeypatch):
    fetched=[]
    def download(url):
        fetched.append(url)
        if 'boards-api' in url:return json.dumps({'title':'AI Architecture Delivery Lead'})
        return '<html><title>Staff Software Engineer @ EliseAI</title></html>'
    monkeypatch.setattr(postings,'_download',download)
    fact=postings.fetch_posting('https://job-boards.greenhouse.io/embed/job_app?for=coretelligent&token=5487133008')
    assert fact['title']=='AI Architecture Delivery Lead'
    assert fetched[0]=='https://boards-api.greenhouse.io/v1/boards/coretelligent/jobs/5487133008'
    assert postings.fetch_posting('https://jobs.ashbyhq.com/eliseai/efc949ef-22ce-401c-8161-091e387e776d/application')['company']=='EliseAI'


def test_workable_metadata_reads_actual_title_from_fixed_public_host(monkeypatch):
    fetched=[]
    def download(url):
        fetched.append(url)
        return '<title>AI Engineer - AI-Powered Detection - Example Cybersecurity, Inc.</title>'
    monkeypatch.setattr(postings,'_download',download)
    url='https://apply.workable.com/example/j/53EA1923CA/?jr_id=tracking'
    fact=postings.fetch_posting(url)
    assert fact is not None
    assert fact['title']=='AI Engineer - AI-Powered Detection'
    assert fact['company']=='Example Cybersecurity, Inc.'
    assert fetched==['https://apply.workable.com/example/j/53EA1923CA/']


def test_verified_workable_title_checks_stale_imported_titles_generally(records,monkeypatch):
    from datetime import date
    from mailcheck.sourcing_fallbacks import prepare_postings
    from mailcheck import sourcing_verification as verification
    conn,_,_,job,receipt=records
    monkeypatch.setattr(verification.payments,'today',lambda:date(2026,11,23))
    rid=job('Example','AI Engineer - Threat Detection Engineering','https://apply.workable.com/example/j/53EA1923CA/')
    receipt('Example Cybersecurity, Inc.','AI Engineer - AI-Powered Threat Detection')
    monkeypatch.setattr(postings,'_download',lambda url:'<title>AI Engineer - AI-Powered Threat Detection - Example Cybersecurity, Inc.</title>')
    prepare_postings(conn,since=date(2026,11,23),until=date(2026,11,23))
    result=verification.verify_all(conn,sample=False)
    assert result['changed']==1
    assert conn.execute('SELECT rule FROM sourcing_match_evidence WHERE row_id=?',(rid,)).fetchone()[0]=='posting_title'


def test_cache_fetches_outside_transactions_and_reuses_results(records,monkeypatch):
    conn,*_=records
    calls=[]
    def fetch(url):
        calls.append(conn.in_transaction)
        return {'title':'Engineer','company':'Acme','url':url}
    monkeypatch.setattr(postings,'fetch_posting',fetch)
    url='https://job-boards.greenhouse.io/acme/jobs/12345'
    postings.warm_postings(conn,[url])
    postings.warm_postings(conn,[url])
    assert calls==[False]
    assert postings.cached_postings(conn,[postings.posting_key(url)])[postings.posting_key(url)]['title']=='Engineer'
    conn.execute("UPDATE bidders SET name=name WHERE id=1")
    postings.warm_postings(conn,[url.replace('12345','67890')])
    assert calls==[False]
    conn.rollback()


def test_unavailable_provider_is_cached_without_failing_verification(records,monkeypatch):
    conn,*_=records
    calls=[]
    def fail(url):
        calls.append(url)
        raise httpx.ConnectTimeout('Provider unavailable')
    monkeypatch.setattr(postings,'fetch_posting',fail)
    url='https://job-boards.greenhouse.io/acme/jobs/12345'
    postings.warm_postings(conn,[url]);postings.warm_postings(conn,[url])
    assert len(calls)==1
    assert not postings.cached_postings(conn,[postings.posting_key(url)])
    assert conn.execute('SELECT status FROM sourcing_posting_cache').fetchone()[0]=='unavailable'


def test_response_limits_and_redirects_do_not_fetch_another_host(monkeypatch):
    class Response:
        status_code=302
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_bytes(self):yield b'x'*(1024*1024+1)
    class Client:
        def __init__(self,**options):assert options['follow_redirects'] is False and options['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,*args,**kwargs):return Response()
    monkeypatch.setattr(postings.httpx,'Client',Client)
    with pytest.raises(ValueError,match='content'):
        postings._download('https://boards-api.greenhouse.io/example')
    Response.status_code=200
    with pytest.raises(ValueError,match='limit'):
        postings._download('https://boards-api.greenhouse.io/example')


def test_public_lookups_have_a_process_wide_concurrency_limit(monkeypatch):
    release=Event();enough=Event();lock=Lock();active=0;maximum=0
    def download(_):
        nonlocal active,maximum
        with lock:
            active+=1;maximum=max(maximum,active)
            if active>=8:enough.set()
        release.wait(timeout=3)
        with lock:active-=1
        return json.dumps({'title':'Engineer'})
    monkeypatch.setattr(postings,'_download',download)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures=[pool.submit(postings.fetch_posting,f'https://job-boards.greenhouse.io/acme/jobs/{10000+i}') for i in range(16)]
        try:
            assert enough.wait(timeout=2)
            time.sleep(.1)
            assert maximum<=8
        finally:release.set()
        for future in futures:
            try:future.result()
            except Exception as exc:
                assert type(exc).__name__=='PostingBusy'


def test_local_lookup_saturation_is_retried_without_negative_cache(records,monkeypatch):
    conn,*_=records
    calls=[]
    def busy(url):
        calls.append(url)
        raise postings.PostingBusy()
    monkeypatch.setattr(postings,'fetch_posting',busy)
    url='https://job-boards.greenhouse.io/acme/jobs/123456'
    postings.warm_postings(conn,[url]);postings.warm_postings(conn,[url])
    assert len(calls)==2
    assert conn.execute('SELECT count(*) FROM sourcing_posting_cache').fetchone()[0]==0
