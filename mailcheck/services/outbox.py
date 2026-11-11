"""Fenced, bounded outbox delivery; no DB connection is held during broker I/O."""
import asyncio
from uuid import UUID, uuid4
from psycopg.rows import dict_row


class OutboxDispatcher:
    def __init__(self,pool,publish):self.pool=pool;self.publish=publish

    async def run_once(self,limit=10):
        if type(limit) is not int or not 1<=limit<=10:raise ValueError('Invalid dispatch batch')
        token=uuid4()
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute('''WITH due AS (
                  SELECT event_id FROM outbox WHERE published_at IS NULL
                   AND next_attempt_at<=clock_timestamp()
                   AND (lease_until IS NULL OR lease_until<clock_timestamp())
                  ORDER BY created_at,event_id LIMIT %s FOR UPDATE SKIP LOCKED)
                  UPDATE outbox o SET lease_token=%s,lease_until=clock_timestamp()+interval '60 seconds',attempts=o.attempts+1
                  FROM due WHERE o.event_id=due.event_id RETURNING o.event_id,o.routing_key,o.payload,o.attempts''',(limit,token))
                records=await cursor.fetchall()
        result={'claimed':len(records),'published':0,'failed':0}
        for record in records:
            try:
                if UUID(str(record['payload'].get('event_id'))) != record['event_id']:
                    raise ValueError('Outbox event identity mismatch')
                async with asyncio.timeout(3):confirmed=await self.publish(record['routing_key'],record['payload'])
                if confirmed is not True:raise RuntimeError('Broker did not confirm publication')
            except Exception:
                async with self.pool.connection() as conn:
                    await conn.execute('''UPDATE outbox SET lease_token=NULL,lease_until=NULL,
                       next_attempt_at=clock_timestamp()+(%s * interval '1 second')
                       WHERE event_id=%s AND lease_token=%s''',(min(60,2**min(6,record['attempts'])),record['event_id'],token))
                result['failed']+=1
            else:
                async with self.pool.connection() as conn:
                    cursor=await conn.execute('''UPDATE outbox SET published_at=clock_timestamp(),lease_token=NULL,lease_until=NULL
                      WHERE event_id=%s AND lease_token=%s AND lease_until>clock_timestamp()''',(record['event_id'],token))
                    result['published']+=cursor.rowcount
        return result
