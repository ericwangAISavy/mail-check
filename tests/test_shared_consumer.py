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
