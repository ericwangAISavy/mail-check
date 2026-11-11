"""Commit-ordered Core journal. Every call releases its pooled connection.

Callers must authorize workspace/account scopes before using this repository.
This module intentionally exposes no HTTP routes or user authentication shortcuts.
"""
from contextlib import asynccontextmanager
import hashlib
import json
import re
from uuid import UUID
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class EventConflict(ValueError):pass
class ResyncRequired(ValueError):pass


def _workspace(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):raise ValueError('Invalid workspace')


class EventJournal:
    def __init__(self,pool):self.pool=pool

    @asynccontextmanager
    async def _connection(self,connection):
        if connection is not None:yield connection
        else:
            async with self.pool.connection() as conn:yield conn

    async def append(self,workspace_id,event_id,account_id,kind,payload,*,connection=None):
        _workspace(workspace_id)
        event_id=UUID(str(event_id))
        if account_id is not None and (not isinstance(account_id,str) or not 1<=len(account_id)<=64):raise ValueError('Invalid account')
        if not isinstance(kind,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{1,99}',kind):raise ValueError('Invalid event kind')
        if not isinstance(payload,dict):raise ValueError('Invalid event payload')
        encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(encoded.encode())>16384:raise ValueError('Event payload is too large')
        fingerprint=hashlib.sha256(json.dumps([account_id,kind,encoded]).encode()).hexdigest()
        async with self._connection(connection) as conn:
            async with conn.transaction():
                await conn.execute('INSERT INTO event_heads(workspace_id) VALUES (%s) ON CONFLICT DO NOTHING',(workspace_id,))
                await conn.execute('SELECT position FROM event_heads WHERE workspace_id=%s FOR UPDATE',(workspace_id,))
                result=await conn.execute('SELECT position,fingerprint FROM journal_event_receipts WHERE workspace_id=%s AND event_id=%s',(workspace_id,event_id))
                old=await result.fetchone()
                if old:
                    if old[1]!=fingerprint:raise EventConflict('Event identity conflicts with existing content')
                    return old[0]
                result=await conn.execute('UPDATE event_heads SET position=position+1 WHERE workspace_id=%s RETURNING position',(workspace_id,))
                position=(await result.fetchone())[0]
                await conn.execute('INSERT INTO journal_event_receipts(workspace_id,event_id,position,fingerprint) VALUES(%s,%s,%s,%s)',(workspace_id,event_id,position,fingerprint))
                await conn.execute('INSERT INTO client_events(workspace_id,position,event_id,account_id,kind,payload,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s)',(workspace_id,position,event_id,account_id,kind,Jsonb(payload),fingerprint))
                await conn.execute("SELECT pg_notify('offerpath_core_events',%s)",(json.dumps({'workspace':workspace_id,'position':position}),))
                return position

    async def barrier(self,workspace_id):
        _workspace(workspace_id)
        async with self.pool.connection() as conn:
            result=await conn.execute('SELECT position FROM event_heads WHERE workspace_id=%s',(workspace_id,))
            row=await result.fetchone()
            return row[0] if row else 0

    async def replay(self,workspace_id,after,limit=100):
        _workspace(workspace_id)
        if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid replay bounds')
        async with self.pool.connection() as conn:
            async with conn.transaction():
                # Short snapshot protects the retention check and read together.
                await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                result=await conn.execute('SELECT position,retained_after FROM event_heads WHERE workspace_id=%s',(workspace_id,))
                row=await result.fetchone() or (0,0)
                if after<row[1]:raise ResyncRequired('Replay cursor expired')
                if after>row[0]:raise ValueError('Replay cursor is ahead of committed state')
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute('SELECT position,event_id,account_id,kind,payload FROM client_events WHERE workspace_id=%s AND position>%s ORDER BY position LIMIT %s',(workspace_id,after,limit))
                    return await cursor.fetchall()

    async def prune_through(self,workspace_id,position):
        _workspace(workspace_id)
        if type(position) is not int or position<0:raise ValueError('Invalid retention boundary')
        async with self.pool.connection() as conn:
            async with conn.transaction():
                result=await conn.execute('SELECT position,retained_after FROM event_heads WHERE workspace_id=%s FOR UPDATE',(workspace_id,))
                row=await result.fetchone()
                if not row:
                    if position:raise ValueError('Unknown journal')
                    return
                if not row[1]<=position<=row[0]:raise ValueError('Invalid retention boundary')
                await conn.execute('DELETE FROM client_events WHERE workspace_id=%s AND position<=%s',(workspace_id,position))
                await conn.execute('UPDATE event_heads SET retained_after=%s WHERE workspace_id=%s',(position,workspace_id))
