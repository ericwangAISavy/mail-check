"""Durable topic routing with independent consumer groups and no silent eviction."""
import asyncio
import base64
import hashlib
import secrets
from .settings import ROLES,read_secret

EXCHANGE='offerpath.events.v1'
BINDINGS={
 'core.live.v1':['mail.live.#','intelligence.match.#','core.workspace.#'],
 'core.backfill.v1':['mail.backfill.#'],
 'mail.results.v1':['intelligence.classification.#','core.workspace.#'],
 'mail.collect.live.v1':['mail.collect.live.#'],
 'mail.collect.backfill.v1':['mail.collect.backfill.#'],
 'intelligence.jobs.v1':['mail.analysis.requested.#'],
}
READ_TOPICS={
 'core':r'^(mail\.(live|backfill)\..*|intelligence\.match\..*|core\.workspace\..*)$',
 'mail':r'^(intelligence\.classification\..*|core\.workspace\..*|mail\.collect\..*)$',
 'intelligence':r'^mail\.analysis\.requested\..*$',
}


def _password_hash(password):
    salt=secrets.token_bytes(4)
    return base64.b64encode(salt+hashlib.sha256(salt+password.encode()).digest()).decode()


def build_definitions(folder):
    return {
      'vhosts':[{'name':'offerpath'}],
      'users':[{'name':f'{role}_events','password_hash':_password_hash(read_secret(folder,f'{role}_broker_password')),
                'hashing_algorithm':'rabbit_password_hashing_sha256','tags':[]} for role in ROLES],
      'permissions':[{'user':f'{role}_events','vhost':'offerpath','configure':rf'^{role}\..*$',
                      'write':r'^offerpath\.events\.v1$','read':rf'^{role}\..*$'} for role in ROLES],
      'topic_permissions':[{'user':f'{role}_events','vhost':'offerpath','exchange':EXCHANGE,
                           'write':rf'^{role}\..*$','read':READ_TOPICS[role]} for role in ROLES],
      'exchanges':[{'name':EXCHANGE,'vhost':'offerpath','type':'topic','durable':True,'auto_delete':False,'internal':False,'arguments':{}}],
      'queues':[{'name':name,'vhost':'offerpath','durable':True,'auto_delete':False,
                 'arguments':{'x-queue-type':'classic','x-max-length-bytes':16*1024*1024,'x-overflow':'reject-publish'}} for name in BINDINGS],
      'bindings':[{'source':EXCHANGE,'vhost':'offerpath','destination':name,'destination_type':'queue','routing_key':key,'arguments':{}}
                  for name,keys in BINDINGS.items() for key in keys],
    }


class BrokerUnavailable(RuntimeError):pass


async def connect(settings):
    import aio_pika
    try:
        return await aio_pika.connect(host=settings.broker_host,port=settings.broker_port,
                  login=f'{settings.role}_events',password=settings.broker_password,virtualhost='offerpath',timeout=2)
    except Exception:
        raise BrokerUnavailable('Broker connection unavailable') from None


class BrokerPublisher:
    """Use as an async context; domain events must already be durably enqueued."""
    def __init__(self,settings):self.settings=settings;self.connection=None

    async def __aenter__(self):
        self.connection=await connect(self.settings)
        try:
            self.channel=await self.connection.channel(publisher_confirms=True,on_return_raises=True)
            self.exchange=await self.channel.get_exchange(EXCHANGE,ensure=False)
        except BaseException:
            await self.connection.close();raise
        return self

    async def __aexit__(self,*_):await self.connection.close()

    async def publish(self,routing_key,payload):
        import json
        import re
        from uuid import UUID
        import aio_pika
        if not isinstance(routing_key,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{1,159}',routing_key) or not routing_key.startswith(self.settings.role+'.'):
            raise ValueError('Event route is outside the publishing domain')
        if not isinstance(payload,dict):raise ValueError('Invalid event payload')
        event_id=UUID(str(payload.get('event_id','')))
        body=json.dumps(payload,separators=(',',':'),allow_nan=False).encode()
        if len(body)>65536:raise ValueError('Event payload is too large')
        async with asyncio.timeout(2):
            confirmation=await self.exchange.publish(aio_pika.Message(body,message_id=str(event_id),content_type='application/json',delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key=routing_key,mandatory=True)
        from pamqp.commands import Basic
        return isinstance(confirmation,Basic.Ack)
