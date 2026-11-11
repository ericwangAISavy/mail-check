import asyncio
import importlib
import json
import os
from pathlib import Path
import pytest
from uuid import uuid4


def test_definitions_use_separate_consumer_groups_and_never_drop_accepted_work(tmp_path):
    module=importlib.import_module('mailcheck.services.broker')
    for role in ['core','mail','intelligence']:(tmp_path/f'{role}_broker_password').write_text('x'*43)
    definitions=module.build_definitions(tmp_path)
    assert len(definitions['users'])==3
    assert 'x'*43 not in json.dumps(definitions)
    assert all(queue['durable'] and queue['arguments']['x-overflow']=='reject-publish' for queue in definitions['queues'])
    bindings=[binding['destination'] for binding in definitions['bindings'] if binding['routing_key']=='core.workspace.#']
    assert set(bindings)=={'core.live.v1','mail.results.v1'}


@pytest.mark.skipif(not os.environ.get('OFFERPATH_TEST_STACK'),reason='requires isolated integration stack')
def test_real_broker_fanout_topic_isolation_and_unroutable_errors():
    import aio_pika
    from aiormq.exceptions import ChannelAccessRefused
    from mailcheck.services.settings import ServiceSettings
    module=importlib.import_module('mailcheck.services.broker')
    cfg=json.loads(Path(os.environ['OFFERPATH_TEST_STACK']).read_text())
    def settings(role):return ServiceSettings.load(role,{'OFFERPATH_SECRET_DIR':cfg['secrets'],'RABBITMQ_HOST':cfg['host'],'RABBITMQ_PORT':str(cfg['broker_port'])})
    async def scenario():
        async with await module.connect(settings('core')) as core, await module.connect(settings('mail')) as mail:
            core_channel=await core.channel(publisher_confirms=True,on_return_raises=True)
            mail_channel=await mail.channel(publisher_confirms=True,on_return_raises=True)
            exchange=await core_channel.get_exchange(module.EXCHANGE,ensure=False)
            payload={'event_id':str(uuid4()),'event':'isolated-test'}
            async with module.BrokerPublisher(settings('core')) as publisher:
                assert await publisher.publish('core.workspace.test.v1',payload) is True
            for channel,name in [(core_channel,'core.live.v1'),(mail_channel,'mail.results.v1')]:
                queue=await channel.get_queue(name,ensure=False)
                message=await queue.get(timeout=2)
                assert json.loads(message.body)==payload
                await message.ack()
            underlay=await mail_channel.get_underlay_channel()
            with pytest.raises(ChannelAccessRefused):
                wrong=await mail_channel.get_queue('core.live.v1',ensure=False)
                await wrong.get(timeout=2)
            with pytest.raises(ChannelAccessRefused):await underlay.closing
        async with await module.connect(settings('mail')) as mail:
            channel=await mail.channel(publisher_confirms=True,on_return_raises=True)
            exchange=await channel.get_exchange(module.EXCHANGE,ensure=False)
            with pytest.raises(aio_pika.exceptions.DeliveryError):
                await exchange.publish(aio_pika.Message(b'{}'),routing_key='mail.unrouted.v1',mandatory=True)
        async with await module.connect(settings('mail')) as mail:
            channel=await mail.channel(publisher_confirms=True,on_return_raises=True)
            exchange=await channel.get_exchange(module.EXCHANGE,ensure=False)
            underlay=await channel.get_underlay_channel()
            with pytest.raises(ChannelAccessRefused):
                await exchange.publish(aio_pika.Message(b'{}'),routing_key='core.workspace.spoof.v1',mandatory=True)
            with pytest.raises(ChannelAccessRefused):await underlay.closing
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('OFFERPATH_TEST_STACK'),reason='requires isolated integration stack')
def test_broker_readiness_detects_a_missing_secondary_owned_queue(monkeypatch):
    from mailcheck.services import dependencies
    from mailcheck.services.settings import ServiceSettings
    module=importlib.import_module('mailcheck.services.broker')
    cfg=json.loads(Path(os.environ['OFFERPATH_TEST_STACK']).read_text())
    settings=ServiceSettings.load('core',{'OFFERPATH_SECRET_DIR':cfg['secrets'],'RABBITMQ_HOST':cfg['host'],'RABBITMQ_PORT':str(cfg['broker_port'])})
    # Disposable queues exercise real AMQP failures without deleting stack work.
    prefix='core.probe.'+uuid4().hex
    primary,secondary=prefix+'.live',prefix+'.backfill'
    assert set(dependencies.QUEUES['core'])=={name for name in module.BINDINGS if name.startswith('core.')}
    monkeypatch.setitem(dependencies.QUEUES,'core',(primary,secondary))
    async def scenario():
        async with await module.connect(settings) as conn:
            channel=await conn.channel()
            first=await channel.declare_queue(primary)
            second=await channel.declare_queue(secondary)
            try:
                assert await dependencies.probe_broker(settings) is True
                await second.delete()
                assert await dependencies.probe_broker(settings) is False
                second=await channel.declare_queue(secondary)
                assert await dependencies.probe_broker(settings) is True
            finally:
                await first.delete()
                await second.delete(if_unused=False,if_empty=False)
    asyncio.run(scenario())
