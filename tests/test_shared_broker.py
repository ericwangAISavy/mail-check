from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import threading
import time
import types
import uuid

import pytest


class Channel:
    def __init__(self):
        self.calls = []
        self.messages = []
        self.delivery = (None, None, None)
        self.error = None
    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, kwargs))
            if name == 'basic_publish':
                if self.error:
                    raise self.error
                self.messages.append(kwargs)
                return True
            if name == 'basic_get':
                return self.delivery
        return call


@pytest.fixture
def broker(monkeypatch):
    from mailcheck.shared.broker import RabbitBroker
    channel = Channel()
    connection = types.SimpleNamespace(channel=lambda: channel, close=lambda: None,
                                       process_data_events=lambda **kw: None)
    monkeypatch.setitem(sys.modules, 'pika', types.SimpleNamespace(
        URLParameters=lambda url: types.SimpleNamespace(),
        BlockingConnection=lambda params: connection,
        BasicProperties=lambda **kwargs: types.SimpleNamespace(**kwargs)))
    return RabbitBroker('amqp://guest:guest@localhost/', workspace_id='legacy'), channel


def test_enqueue_confirmed_persistent_and_fixed_topology(broker):
    b, ch = broker
    job = b.enqueue('mail', 1)
    body = json.loads(ch.messages[0]['body'])
    assert str(uuid.UUID(job)) == job
    assert body == dict(version=1, id=job, workspace_id='legacy', account_id=1,
                        kind='mail', reason='notification', attempt=0, payload={}, dispatch_id=None)
    assert ch.messages[0]['mandatory'] is True
    assert ch.messages[0]['properties'].delivery_mode == 2
    assert ('confirm_delivery', {}) in ch.calls
    assert ('basic_qos', {'prefetch_count': 1}) in ch.calls
    queues = [kw for name, kw in ch.calls if name == 'queue_declare']
    assert queues and all(q['durable'] and q['arguments']['x-queue-type'] == 'quorum' for q in queues)


@pytest.mark.parametrize('kwargs', [dict(kind='evil'), dict(workspace_id='../evil'),
    dict(account_id=''), dict(payload={'password': 'secret'}), dict(job_id='invalid')])
def test_invalid_envelopes_rejected_before_publish(broker, kwargs):
    b, ch = broker
    args = dict(kind='mail', account_id=1)
    args.update(kwargs)
    with pytest.raises((ValueError, TypeError)):
        b.enqueue(**args)
    assert not ch.messages


def test_claim_poison_rejected_and_valid_claim_manual_ack(broker):
    b, ch = broker
    ch.delivery = (types.SimpleNamespace(delivery_tag=7), None, b'{}')
    assert b.claim('mail') is None
    assert ('basic_reject', dict(delivery_tag=7, requeue=False)) in ch.calls
    b.enqueue('mail', 1)
    ch.delivery = (types.SimpleNamespace(delivery_tag=8), None, ch.messages[-1]['body'])
    tag, fields = b.claim('mail')
    assert tag == 8 and fields['account_id'] == 1
    assert not any(name == 'basic_ack' for name, kw in ch.calls)
    b.ack(tag)
    assert ch.calls[-1] == ('basic_ack', dict(delivery_tag=8))


def test_retry_confirmation_precedes_ack_and_keeps_original_on_failure(broker):
    b, ch = broker
    b.enqueue('mail', 1)
    fields = json.loads(ch.messages[-1]['body'])
    ch.error = RuntimeError('unavailable')
    with pytest.raises(RuntimeError):
        b.fail(9, fields)
    assert not any(name == 'basic_ack' for name, kw in ch.calls)
    ch.error = None
    b.fail(9, fields)
    assert json.loads(ch.messages[-1]['body'])['attempt'] == 1
    assert ch.calls[-1] == ('basic_ack', dict(delivery_tag=9))
    fields['attempt'] = 4
    b.fail(10, fields)
    assert 'dead' in ch.messages[-1]['routing_key']


def test_changes_have_durable_sink_and_confirmed_route(broker):
    b, ch = broker
    b.publish(['mail', 'calendar'], 12)
    msg = ch.messages[-1]
    assert msg['mandatory'] and json.loads(msg['body'])['workspace_id'] == 'legacy'
    assert any(name == 'queue_bind' and kw.get('routing_key') == 'changes.#' for name, kw in ch.calls)


def test_real_rabbit_round_trip():
    url = os.environ.get('OFFERPATH_TEST_AMQP_URL')
    if not url:
        pytest.skip('set OFFERPATH_TEST_AMQP_URL for isolated broker integration')
    from mailcheck.shared.broker import RabbitBroker
    b = RabbitBroker(url, workspace_id='legacy')
    try:
        identifier = b.enqueue('mail', 2147483647)
        result = b.claim('mail')
        assert result and result[1]['id'] == identifier
        b.ack(result[0])
    finally:
        b.close()


def test_real_rabbit_redelivers_after_worker_process_exits():
    url = os.environ.get('OFFERPATH_TEST_AMQP_URL')
    if not url:
        pytest.skip('set OFFERPATH_TEST_AMQP_URL for isolated broker integration')
    from mailcheck.shared.broker import RabbitBroker

    broker = RabbitBroker(url, workspace_id='legacy')
    try:
        identifier = broker.enqueue('calendar-analysis', 0, reason='reconcile')
        result = subprocess.run([sys.executable, '-c', """
import os
from mailcheck.shared.broker import RabbitBroker
broker = RabbitBroker(os.environ['OFFERPATH_TEST_AMQP_URL'])
delivery = broker.claim('calendar-analysis')
print(delivery[1]['id'], flush=True)
os._exit(0)
"""], capture_output=True, text=True, timeout=20, check=True)
        assert result.stdout.strip() == identifier
        deadline = time.monotonic() + 5
        while (delivery := broker.claim('calendar-analysis')) is None and time.monotonic() < deadline:
            broker.process_events(.05)
        assert delivery and delivery[1]['id'] == identifier
        broker.ack(delivery[0])
    finally:
        broker.close()


def test_real_rabbit_retry_delay_and_terminal_notice():
    url = os.environ.get('OFFERPATH_TEST_AMQP_URL')
    if not url:
        pytest.skip('set OFFERPATH_TEST_AMQP_URL for isolated broker integration')
    from mailcheck.shared.broker import JOBS_EXCHANGE, MAX_ATTEMPTS, RabbitBroker

    broker = RabbitBroker(url, workspace_id='legacy')
    kind = 'scheduled-check'
    try:
        identifier = broker.enqueue(kind, 0, reason='reconcile')
        tag, fields = broker.claim(kind)
        broker.fail(tag, fields)
        assert broker.claim(kind) is None
        deadline = time.monotonic() + 12
        while (delivery := broker.claim(kind)) is None and time.monotonic() < deadline:
            broker.process_events(.05)
        assert delivery and delivery[1]['id'] == identifier and delivery[1]['attempt'] == 1
        broker.ack(delivery[0])

        # Seed the final attempt directly instead of waiting out every retry tier.
        broker._publish(JOBS_EXCHANGE, kind, {**fields, 'attempt': MAX_ATTEMPTS - 1})
        broker.fail(*broker.claim(kind))
        notice = broker.claim_dead_notice()
        assert notice and notice[1]['id'] == identifier
        broker.ack(notice[0])
    finally:
        broker.close()


def test_explicit_id_is_stable_and_retry_does_not_mutate_original(broker):
    b, ch = broker
    identifier = str(uuid.uuid4())
    assert b.enqueue('classify', 1, job_id=identifier) == identifier
    fields = json.loads(ch.messages[-1]['body'])
    b.fail(1, fields)
    assert fields['attempt'] == 0
    assert json.loads(ch.messages[-1]['body'])['id'] == identifier


@pytest.mark.parametrize('mutate', [lambda f: f.update(extra='bad'),
    lambda f: f.update(attempt=True), lambda f: f.update(attempt=5),
    lambda f: f.update(version=True), lambda f: f.update(kind='calendar')])
def test_claim_rejects_unsupported_schema_and_wrong_queue(broker, mutate):
    b, ch = broker
    b.enqueue('mail', 1)
    fields = json.loads(ch.messages[-1]['body'])
    mutate(fields)
    ch.delivery = (types.SimpleNamespace(delivery_tag=2), None, json.dumps(fields).encode())
    assert b.claim('mail') is None
    assert ch.calls[-1] == ('basic_reject', dict(delivery_tag=2, requeue=False))


def test_lazy_connection_missing_url_and_owner_heartbeat(broker, monkeypatch):
    b, ch = broker
    assert b._connection is None
    b.process_events(time_limit=0)
    assert b._connection is not None
    monkeypatch.delenv('AMQP_URL', raising=False)
    from mailcheck.shared.broker import RabbitBroker
    missing = RabbitBroker()
    with pytest.raises(RuntimeError, match='AMQP_URL'):
        missing.claim('mail')
    b.close()
    assert b._connection is None


def test_channel_open_failure_closes_half_open_connection(monkeypatch):
    from mailcheck.shared.broker import RabbitBroker

    closed = []

    def open_channel():
        raise OSError('channel unavailable')

    connection = types.SimpleNamespace(channel=open_channel, close=lambda: closed.append(True))
    monkeypatch.setitem(sys.modules, 'pika', types.SimpleNamespace(
        URLParameters=lambda url: types.SimpleNamespace(),
        BlockingConnection=lambda params: connection,
    ))
    broker = RabbitBroker('amqp://test', workspace_id='legacy')
    with pytest.raises(OSError, match='channel unavailable'):
        broker.enqueue('mail', 1)
    assert closed == [True]
    assert broker._connection is None


def test_slow_collection_confirm_does_not_block_model_admission(tmp_path):
    from mailcheck.shared.broker import RabbitBroker

    collection_publishing = threading.Event()
    release_collection = threading.Event()
    model_publishing = threading.Event()

    class Broker(RabbitBroker):
        def _publish(self, exchange, routing_key, body):
            if routing_key == 'mail':
                collection_publishing.set()
                assert release_collection.wait(5)
            else:
                model_publishing.set()

    def enqueue(kind):
        return Broker(workspace_id='legacy').enqueue_unique(kind, 1, coordination_root=tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(enqueue, 'mail')
        try:
            assert collection_publishing.wait(3)
            second = executor.submit(enqueue, 'classify')
            assert model_publishing.wait(1)
        finally:
            release_collection.set()
        assert first.result() != second.result()


def test_reconciliation_does_not_rewrite_an_unchanged_marker(broker, tmp_path, monkeypatch):
    from mailcheck.shared import state

    b, _ = broker
    job = b.enqueue_unique('mail', 1, coordination_root=tmp_path)

    def unexpected_write(*args):
        pytest.fail('Existing clean marker should not be rewritten during reconciliation')

    monkeypatch.setattr(state, 'atomic_json', unexpected_write)
    assert b.enqueue_unique('mail', 1, coordination_root=tmp_path, dirty_existing=False) == job


@pytest.mark.parametrize('account_id', [0, -1, True, '1'])
def test_account_identity_requires_positive_database_id(broker, account_id):
    b, ch = broker
    with pytest.raises(ValueError):
        b.enqueue('mail', account_id)
    assert not ch.messages


def test_manual_workspace_jobs_require_dispatch_provenance(broker):
    b, ch = broker
    with pytest.raises(ValueError):
        b.enqueue('manual-check', 0, reason='manual')
    dispatch = str(uuid.uuid4())
    b.enqueue('manual-check', 0, reason='manual', dispatch_id=dispatch)
    assert json.loads(ch.messages[-1]['body'])['dispatch_id'] == dispatch
    b.enqueue('calendar-analysis', 0, reason='reconcile')
    with pytest.raises(ValueError):
        b.enqueue('mail', 1, reason='manual')
    with pytest.raises(ValueError):
        b.enqueue('mail', 1, dispatch_id=dispatch)
    with pytest.raises(ValueError):
        b.enqueue('mail', 1, reason='untrusted')


def test_scheduled_checks_are_workspace_scoped_without_manual_provenance(broker):
    b, ch = broker
    b.enqueue('scheduled-check', 0, reason='reconcile')
    with pytest.raises(ValueError):
        b.enqueue('scheduled-check', 1, reason='reconcile')
    with pytest.raises(ValueError):
        b.enqueue('scheduled-check', 0)


def test_unique_coalesces_then_publishes_one_followup(broker, tmp_path):
    b, ch = broker
    first = b.enqueue_unique('mail', 1, coordination_root=tmp_path)
    fields = json.loads(ch.messages[-1]['body'])
    assert b.enqueue_unique('mail', 1, coordination_root=tmp_path) == first
    assert len(ch.messages) == 1
    b.complete_unique(fields, tmp_path)
    assert len(ch.messages) == 2
    followup = json.loads(ch.messages[-1]['body'])
    assert followup['id'] != first
    b.complete_unique(fields, tmp_path)  # stale delivery cannot delete new marker
    assert b.enqueue_unique('mail', 1, coordination_root=tmp_path) == followup['id']
    assert len(ch.messages) == 2


def test_periodic_reconcile_does_not_keep_capacity_permanently_occupied(broker,tmp_path):
    b,ch=broker
    fields=[]
    for account in range(1,17):
        b.enqueue_unique('mail',account,'reconcile',coordination_root=tmp_path,dirty_existing=False)
        fields.append(json.loads(ch.messages[-1]['body']))
    for account in range(1,17):
        b.enqueue_unique('mail',account,'reconcile',coordination_root=tmp_path,dirty_existing=False)
    for item in fields:
        b.complete_unique(item,tmp_path)
    assert not list(tmp_path.glob('*/pending/*.json'))
    b.enqueue_unique('mail',17,'reconcile',coordination_root=tmp_path,dirty_existing=False)
    assert json.loads(ch.messages[-1]['body'])['account_id']==17


def test_unique_uncertain_publish_retains_identity(broker, tmp_path):
    b, ch = broker
    ch.error = RuntimeError('uncertain')
    with pytest.raises(RuntimeError):
        b.enqueue_unique('calendar', 1, coordination_root=tmp_path)
    marker = json.loads(next(tmp_path.glob('*/pending/*.json')).read_text())
    ch.error = None
    assert b.enqueue_unique('calendar', 1, coordination_root=tmp_path) == marker['id']
    fields = json.loads(ch.messages[-1]['body'])
    b.abandon_unique(fields, tmp_path)
    assert b.enqueue_unique('calendar', 1, coordination_root=tmp_path) != marker['id']


def test_unique_completion_publication_failure_preserves_dirty_marker(broker, tmp_path):
    b, ch = broker
    b.enqueue_unique('mail', 1, coordination_root=tmp_path)
    fields = json.loads(ch.messages[-1]['body'])
    b.enqueue_unique('mail', 1, coordination_root=tmp_path)
    ch.error = RuntimeError('uncertain')
    with pytest.raises(RuntimeError):
        b.complete_unique(fields, tmp_path)
    marker = json.loads(next(tmp_path.glob('*/pending/*.json')).read_text())
    assert marker['id'] == fields['id'] and marker['dirty']
    ch.error = None
    b.complete_unique(fields, tmp_path)
    followup = json.loads(ch.messages[-1]['body'])
    b.complete_unique(followup, tmp_path)
    assert not list(tmp_path.glob('*/pending/*.json'))


def test_live_inbox_schedule_is_workspace_only(broker):
    b, ch = broker
    b.enqueue('live-inbox', 0, reason='startup')
    with pytest.raises(ValueError):
        b.enqueue('live-inbox', 1, reason='startup')
    with pytest.raises(ValueError):
        b.enqueue('live-inbox', 0, reason='poll')


def test_unique_followup_identity_survives_lost_confirm(broker, tmp_path):
    b, ch = broker
    b.enqueue_unique('classify', 1, coordination_root=tmp_path)
    fields = json.loads(ch.messages[-1]['body'])
    b.enqueue_unique('classify', 1, coordination_root=tmp_path)
    original_publish = ch.basic_publish
    attempted = []
    def uncertain(**kwargs):
        attempted.append(json.loads(kwargs['body'])['id'])
        raise RuntimeError('confirmation lost')
    ch.basic_publish = uncertain
    for _ in range(2):
        with pytest.raises(RuntimeError):
            b.complete_unique(fields, tmp_path)
    assert attempted[0] == attempted[1]
    ch.basic_publish = original_publish
    b.complete_unique(fields, tmp_path)
    assert json.loads(ch.messages[-1]['body'])['id'] == attempted[0]


def test_unique_scope_and_no_dirty_completion_clear_marker(broker, tmp_path):
    b, ch = broker
    first = b.enqueue_unique('mail', 1, coordination_root=tmp_path)
    first_fields = json.loads(ch.messages[-1]['body'])
    other = b.enqueue_unique('mail', 1, workspace_id='a' * 32, coordination_root=tmp_path)
    assert first != other
    b.complete_unique(first_fields, tmp_path)
    assert b.enqueue_unique('mail', 1, coordination_root=tmp_path) != first
    assert len(list(tmp_path.glob('*/pending/*.json'))) == 2


def test_unique_workspace_capacity_defers_new_accounts_only(broker, tmp_path):
    from mailcheck.shared.broker import PendingCapacityError
    b, ch = broker
    for account in range(1, 17):
        b.enqueue_unique('mail', account, coordination_root=tmp_path)
    with pytest.raises(PendingCapacityError):
        b.enqueue_unique('mail', 17, coordination_root=tmp_path)
    assert len(ch.messages) == 16
    b.enqueue_unique('mail', 1, coordination_root=tmp_path)
    b.enqueue_unique('mail', 17, workspace_id='a' * 32, coordination_root=tmp_path)
    assert len(ch.messages) == 17


@pytest.mark.parametrize('first,second',[('mail','classify'),('classify','mail')])
def test_collection_and_model_hints_have_independent_capacity(broker,tmp_path,first,second):
    from mailcheck.shared.broker import PendingCapacityError
    b,ch=broker
    for account in range(1,17):
        b.enqueue_unique(first,account,coordination_root=tmp_path)
    with pytest.raises(PendingCapacityError):
        b.enqueue_unique(first,17,coordination_root=tmp_path)
    b.enqueue_unique(second,17,coordination_root=tmp_path)
    assert len(ch.messages)==17


def test_dead_notices_have_separate_queue_and_validate_envelope(broker):
    from mailcheck.shared.broker import DEAD_NOTICES_QUEUE
    b, ch = broker
    b.enqueue('mail', 1)
    body = ch.messages[-1]['body']
    assert any(name == 'queue_bind' and kw.get('queue') == DEAD_NOTICES_QUEUE
               and kw.get('routing_key') == 'dead.mail' for name, kw in ch.calls)
    ch.delivery = (types.SimpleNamespace(delivery_tag=88), None, body)
    tag, fields = b.claim_dead_notice()
    assert tag == 88 and fields['kind'] == 'mail'
    assert ch.calls[-1] == ('basic_get', dict(queue=DEAD_NOTICES_QUEUE, auto_ack=False))
    ch.delivery = (types.SimpleNamespace(delivery_tag=89), None, b'{}')
    assert b.claim_dead_notice() is None
    assert ch.calls[-1] == ('basic_reject', dict(delivery_tag=89, requeue=False))


def test_defer_confirms_same_envelope_without_spending_retry_budget(broker):
    b, ch = broker
    b.enqueue('mail', 1)
    fields = json.loads(ch.messages[-1]['body'])
    fields['attempt'] = 4
    b.defer(42, fields)
    assert ch.messages[-1]['routing_key'] == 'retry.mail.0'
    assert json.loads(ch.messages[-1]['body']) == fields
    assert ch.messages[-1]['properties'].delivery_mode == 2
    assert ch.calls[-1] == ('basic_ack', dict(delivery_tag=42))


def test_defer_publish_failure_preserves_original_delivery(broker):
    b, ch = broker
    b.enqueue('mail', 1)
    fields = json.loads(ch.messages[-1]['body'])
    ch.error = ConnectionError('unavailable')
    with pytest.raises(ConnectionError):
        b.defer(42, fields)
    assert not any(name == 'basic_ack' for name, _ in ch.calls)
