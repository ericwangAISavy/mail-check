import time
import uuid

import pytest

from mailcheck.realtime.runtime import WorkDeferred
from mailcheck.shared.broker import PendingCapacityError
from mailcheck.shared.runtime import Consumer


@pytest.mark.parametrize('failure',[WorkDeferred('busy'),PendingCapacityError('full')])
def test_admission_wait_does_not_consume_business_retry_budget(tmp_path,monkeypatch,failure):
    from types import SimpleNamespace
    from mailcheck.shared import runtime
    fields=dict(version=1,id=str(uuid.uuid4()),workspace_id='legacy',account_id=1,
                kind='mail',reason='reconcile',attempt=4,payload={},dispatch_id=None)
    consumer=Consumer(SimpleNamespace(root=tmp_path),(),'amqp://test','collection')
    calls=[]
    class Broker:
        def claim(self,kind):return 7,fields
        def process_events(self,limit):time.sleep(.001)
        def defer(self,tag,body):calls.append(('defer',tag,body['attempt']));consumer.stop.set()
        def fail(self,tag,body):calls.append(('fail',tag,body['attempt']));consumer.stop.set()
        def close(self):pass
    monkeypatch.setattr(runtime,'RabbitBroker',lambda *args:Broker())
    def execute(*args):raise failure
    monkeypatch.setattr(runtime,'execute_job',execute)
    consumer.run()
    assert calls==[('defer',7,4)]


def test_collection_failure_logs_workspace_and_account_without_private_error_text(tmp_path,monkeypatch,caplog):
    from types import SimpleNamespace
    from mailcheck.shared import runtime
    from mailcheck.sources.base import SourceError
    fields=dict(version=1,id=str(uuid.uuid4()),workspace_id='legacy',account_id=1,
                kind='mail',reason='reconcile',attempt=0,payload={},dispatch_id=None)
    consumer=Consumer(SimpleNamespace(root=tmp_path),(),'amqp://test','collection')
    failed=[]
    class Broker:
        def claim(self,kind):return 7,fields
        def process_events(self,limit):time.sleep(.001)
        def fail(self,tag,body):failed.append(tag);consumer.stop.set()
        def close(self):pass
    monkeypatch.setattr(runtime,'RabbitBroker',lambda *args:Broker())
    def execute(*args):raise SourceError('private provider response and credentials')
    monkeypatch.setattr(runtime,'execute_job',execute)
    consumer.run()
    assert failed==[7]
    assert 'workspace=legacy account=1 kind=mail attempt=1 error=SourceError' in caplog.text
    assert 'private provider response' not in caplog.text
    assert 'raised_at=test_shared_consumer.py:' in caplog.text and 'in execute' in caplog.text
