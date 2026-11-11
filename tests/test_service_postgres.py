"""Opt-in real PostgreSQL tests; never touch a production database."""
import asyncio
import importlib
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest

pytestmark=pytest.mark.skipif(not os.environ.get('OFFERPATH_TEST_STACK'),reason='requires isolated service integration stack')


def service(role='core'):
    from mailcheck.services.settings import ServiceSettings
    cfg=json.loads(Path(os.environ['OFFERPATH_TEST_STACK']).read_text())
    return ServiceSettings.load(role,{'OFFERPATH_SECRET_DIR':cfg['secrets'],'POSTGRES_HOST':cfg['host'],'POSTGRES_PORT':str(cfg['postgres_port']),'RABBITMQ_HOST':cfg['host'],'RABBITMQ_PORT':str(cfg['broker_port'])})


def test_migrations_are_repeatable_and_runtime_cannot_create_or_cross_databases():
    import psycopg
    db=importlib.import_module('mailcheck.services.database')
    settings=service()
    db.migrate_domain(settings);db.migrate_domain(settings)
    with psycopg.connect(**settings.db_kwargs(),autocommit=True) as conn:
        assert conn.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()==[(1,),(2,),(3,)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute('CREATE TABLE forbidden(id int)')
    wrong=settings.db_kwargs();wrong['dbname']='offerpath_mail'
    with pytest.raises(psycopg.OperationalError):psycopg.connect(**wrong)


def test_journal_deduplicates_and_isolates_workspaces():
    from psycopg_pool import AsyncConnectionPool
    module=importlib.import_module('mailcheck.services.journal')
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=4,open=False) as pool:
            journal=module.EventJournal(pool);workspace=uuid4().hex;event=uuid4()
            assert await journal.append(workspace,event,'account-a','mail.changed',{'revision':1})==1
            assert await journal.append(workspace,event,'account-a','mail.changed',{'revision':1})==1
            with pytest.raises(module.EventConflict):await journal.append(workspace,event,'account-b','mail.changed',{'revision':2})
            assert await journal.barrier(workspace)==1
            assert len(await journal.replay(workspace,0))==1
            assert await journal.replay(uuid4().hex,0)==[]
            await journal.prune_through(workspace,1)
            with pytest.raises(module.ResyncRequired):await journal.replay(workspace,0)
            with pytest.raises(ValueError):await journal.replay(workspace,2)
    asyncio.run(scenario())


def test_journal_barrier_never_skips_a_late_transaction():
    from psycopg_pool import AsyncConnectionPool
    from psycopg.types.json import Jsonb
    module=importlib.import_module('mailcheck.services.journal')
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=4,open=False) as pool:
            workspace=uuid4().hex;journal=module.EventJournal(pool)
            async with pool.connection() as conn:
                await conn.execute('INSERT INTO event_heads(workspace_id) VALUES (%s)',(workspace,));await conn.commit()
                async with conn.transaction():
                    await conn.execute('UPDATE event_heads SET position=1 WHERE workspace_id=%s',(workspace,))
                    await conn.execute('INSERT INTO client_events(workspace_id,position,event_id,account_id,kind,payload,fingerprint) VALUES (%s,1,%s,%s,%s,%s,%s)',(workspace,uuid4(),'a','mail.changed',Jsonb({'revision':1}),'manual-fixture'))
                    later=asyncio.create_task(journal.append(workspace,uuid4(),'a','mail.changed',{'revision':2}))
                    await asyncio.sleep(.05)
                    assert not later.done()
                    assert await journal.barrier(workspace)==0
                assert await later==2
            assert [row['position'] for row in await journal.replay(workspace,0)]==[1,2]
    asyncio.run(scenario())


def test_journal_pruning_does_not_forget_processed_event_identity():
    from psycopg_pool import AsyncConnectionPool
    module=importlib.import_module('mailcheck.services.journal')
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=2,open=False) as pool:
            journal=module.EventJournal(pool);workspace=uuid4().hex;event=uuid4()
            await journal.append(workspace,event,'a','mail.changed',{})
            await journal.prune_through(workspace,1)
            assert await journal.append(workspace,event,'a','mail.changed',{})==1
            assert await journal.barrier(workspace)==1
    asyncio.run(scenario())


def test_journal_can_join_the_consumers_business_transaction():
    from psycopg_pool import AsyncConnectionPool
    module=importlib.import_module('mailcheck.services.journal')
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=1,open=False) as pool:
            journal=module.EventJournal(pool);workspace=uuid4().hex
            with pytest.raises(RuntimeError):
                async with pool.connection() as conn:
                    async with conn.transaction():
                        await journal.append(workspace,uuid4(),'a','mail.changed',{},connection=conn)
                        raise RuntimeError('business projection failed')
            assert await journal.barrier(workspace)==0
    asyncio.run(scenario())


def test_outbox_does_not_hold_a_connection_while_publishing_and_retains_failures():
    from psycopg_pool import AsyncConnectionPool
    from psycopg.types.json import Jsonb
    module=importlib.import_module('mailcheck.services.outbox')
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=1,open=False,timeout=.3) as pool:
            event=uuid4()
            async with pool.connection() as conn:
                await conn.execute('INSERT INTO outbox(event_id,routing_key,payload) VALUES(%s,%s,%s)',(event,'core.workspace.test.v1',Jsonb({'event_id':str(event)})))
            async def publish(key,payload):
                async with pool.connection() as conn:assert (await (await conn.execute('SELECT 1')).fetchone())==(1,)
                raise RuntimeError('broker unavailable')
            result=await module.OutboxDispatcher(pool,publish).run_once()
            assert result['failed']>=1
            async with pool.connection() as conn:
                row=await (await conn.execute('SELECT published_at,lease_token,attempts FROM outbox WHERE event_id=%s',(event,))).fetchone()
                assert row==(None,None,1)
                await conn.execute('DELETE FROM outbox WHERE event_id=%s',(event,))
            async def confirmed(key,payload):return True
            async with pool.connection() as conn:await conn.execute('INSERT INTO outbox(event_id,routing_key,payload) VALUES(%s,%s,%s)',(event,'core.workspace.test.v1',Jsonb({'event_id':str(event)})))
            result=await module.OutboxDispatcher(pool,confirmed).run_once()
            assert result['published']>=1
            async with pool.connection() as conn:
                assert (await (await conn.execute('SELECT published_at IS NOT NULL FROM outbox WHERE event_id=%s',(event,))).fetchone())[0]
                await conn.execute('DELETE FROM outbox WHERE event_id=%s',(event,))
    asyncio.run(scenario())


def test_provisioning_rejects_unexpected_role_memberships():
    import psycopg
    from mailcheck.services.provision import provision_domains
    from mailcheck.services.settings import read_secret
    settings=service()
    admin={**settings.db_kwargs(),'dbname':'postgres','user':'postgres','password':read_secret(settings.secret_dir,'postgres_admin_password')}
    with psycopg.connect(**admin,autocommit=True) as conn:
        conn.execute('GRANT core_owner TO core_app')
        try:
            with pytest.raises(ValueError,match='membership'):
                provision_domains(settings.secret_dir,settings.postgres_host,settings.postgres_port)
        finally:
            conn.execute('REVOKE core_owner FROM core_app')


def test_outbox_rejects_payload_identity_mismatch():
    from psycopg_pool import AsyncConnectionPool
    from psycopg.types.json import Jsonb
    from mailcheck.services.outbox import OutboxDispatcher
    async def scenario():
        async with AsyncConnectionPool(kwargs=service().db_kwargs(),min_size=0,max_size=1,open=False) as pool:
            event=uuid4();published=[]
            async with pool.connection() as conn:
                await conn.execute('INSERT INTO outbox(event_id,routing_key,payload) VALUES(%s,%s,%s)',(event,'core.workspace.test.v1',Jsonb({'event_id':str(uuid4())})))
            async def publish(key,payload):published.append(payload);return True
            try:
                result=await OutboxDispatcher(pool,publish).run_once()
                assert result['failed']>=1 and not published
                async with pool.connection() as conn:
                    assert (await (await conn.execute('SELECT published_at FROM outbox WHERE event_id=%s',(event,))).fetchone())==(None,)
            finally:
                async with pool.connection() as conn:await conn.execute('DELETE FROM outbox WHERE event_id=%s',(event,))
    asyncio.run(scenario())


def test_provisioning_rejects_replication_privilege():
    import psycopg
    from mailcheck.services.provision import provision_domains
    from mailcheck.services.settings import read_secret
    settings=service()
    admin={**settings.db_kwargs(),'dbname':'postgres','user':'postgres','password':read_secret(settings.secret_dir,'postgres_admin_password')}
    with psycopg.connect(**admin,autocommit=True) as conn:
        conn.execute('ALTER ROLE core_app REPLICATION')
        try:
            with pytest.raises(ValueError,match='unsafe attributes'):
                provision_domains(settings.secret_dir,settings.postgres_host,settings.postgres_port)
        finally:conn.execute('ALTER ROLE core_app NOREPLICATION')
