"""Short independent probes; no dependency failure can block liveness."""
import asyncio

from .broker import BINDINGS

# Probe every owned consumer group; a missing backfill/collection queue must
# never be hidden by the main live queue still being available.
QUEUES={role:tuple(name for name in BINDINGS if name.startswith(role+'.'))
        for role in ('core','mail','intelligence')}


async def probe_postgres(settings):
    try:
        import psycopg
        from .database import expected_schema_version
        async with await psycopg.AsyncConnection.connect(**settings.db_kwargs()) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1')
                return (await cursor.fetchone())==(expected_schema_version(settings.role),)
    except Exception:return False


async def probe_broker(settings):
    try:
        from .broker import connect
        conn=await connect(settings)
        async with conn:
            channel=await conn.channel()
            for name in QUEUES[settings.role]:
                await channel.declare_queue(name,passive=True)
        return True
    except Exception:return False


async def probe_dependencies(settings):
    database,broker=await asyncio.gather(probe_postgres(settings),probe_broker(settings))
    return {'postgres':database,'rabbitmq':broker}
