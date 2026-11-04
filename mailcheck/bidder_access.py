"""Globally named bidder credentials; no mailbox or payment data lives here."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

from .control_store import RevokedSession
from .web.auth import _password, _record

# Explicit endpoints, never prefix-based access to future admin routes.
VIEWER_APIS = frozenset(('/api/applications/today', '/api/bootstrap', '/api/dashboard', '/api/dashboard/accounts',
                         '/api/payments', '/api/payments/activity', '/api/sourcing', '/api/sourcing/search'))
VIEWER_PAGES = frozenset(('/', '/dashboard', '/payments', '/login', '/sourcing'))


def viewer_read_allowed(path, method):
    import re
    return method in ('GET', 'HEAD') and (path in VIEWER_APIS or path in VIEWER_PAGES
        or re.fullmatch(r'/api/sourcing/tabs/[0-9]+',path) is not None
        or path.startswith('/api/messages/') and path.removeprefix('/api/messages/').isascii()
        and path.removeprefix('/api/messages/').isdigit())


def username_key(name):
    return unicodedata.normalize('NFKC',name).strip().casefold()


class BidderAccess:
    def __init__(self, store):
        self.store = store
        with store.connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS bidder_logins(
              id INTEGER PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
              bidder_id INTEGER NOT NULL,name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,
              salt TEXT,hash TEXT,version TEXT NOT NULL,UNIQUE(workspace_id,bidder_id));
            CREATE TABLE IF NOT EXISTS bidder_sessions(
              token_hash TEXT PRIMARY KEY,login_id INTEGER NOT NULL REFERENCES bidder_logins(id),
              version TEXT NOT NULL,admin_version TEXT NOT NULL,owner_version TEXT,expires REAL NOT NULL);
            ''')
            if 'username_key' not in {r[1] for r in conn.execute('PRAGMA table_info(bidder_logins)')}:
                conn.execute('ALTER TABLE bidder_logins ADD COLUMN username_key TEXT')
            for row in conn.execute("SELECT id,name FROM bidder_logins WHERE username_key IS NULL AND NOT (enabled=0 AND name='Removed bidder')").fetchall():
                conn.execute('UPDATE bidder_logins SET username_key=? WHERE id=?',(username_key(row['name']),row['id']))
            conn.execute("UPDATE bidder_logins SET username_key=NULL WHERE enabled=0 AND name='Removed bidder'")
            # Nonunique for older installations: ambiguous legacy names must fail closed.
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bidder_login_username ON bidder_logins(username_key)')

    def check_username(self,name,workspace,bidder_id,legacy_database):
        '''Called under the gateway's bidder-write lock before any worker mutation.

        Read existing business records, including paused accounts and bidders without
        passwords. Keeping the check next to the worker write avoids a second registry
        becoming stale after a restart or a failed worker request.
        '''
        key=username_key(name)
        with self.store.connect() as conn:
            workspaces=conn.execute('''SELECT w.id,w.root FROM workspaces w
                JOIN users u ON u.workspace_id=w.id WHERE u.removed_at IS NULL''').fetchall()
            fallbacks=conn.execute('''SELECT b.workspace_id,b.bidder_id,b.name FROM bidder_logins b
                JOIN users u ON u.workspace_id=b.workspace_id WHERE u.removed_at IS NULL AND b.username_key IS NOT NULL''').fetchall()
        def conflict(records,wid):
            return any(username_key(other)==key and (wid!=workspace or who!=bidder_id) for who,other in records)
        if any(username_key(r['name'])==key and (r['workspace_id']!=workspace or r['bidder_id']!=bidder_id) for r in fallbacks):
            raise ValueError('That bidder username is already in use. Choose another.')
        for item in workspaces:
            wid=item['id']
            database=Path(item['root'])/'data'/'mailcheck.db' if item['root'] else Path(legacy_database)
            if database.is_file():
                try:
                    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as source:
                        columns={r[1] for r in source.execute('PRAGMA table_info(bidders)')}
                        if columns:
                            # Stream rows and stop on the first match instead of loading
                            # every workspace's bidder roster into memory.
                            records=source.execute('SELECT id,name FROM bidders'+(' WHERE removed_at IS NULL' if 'removed_at' in columns else ''))
                            if conflict(records,wid):raise ValueError('That bidder username is already in use. Choose another.')
                except (sqlite3.Error,OSError) as exc:
                    raise RuntimeError('Could not check bidder usernames. Retry when all workspace databases are available.') from exc

    def directory(self):
        with self.store.connect() as conn:
            return [{'id':r['id'],'name':r['name']} for r in conn.execute('''
              SELECT b.id,b.name,u.username FROM bidder_logins b
              JOIN workspaces w ON w.id=b.workspace_id JOIN users u ON u.workspace_id=w.id
              WHERE b.enabled=1 AND w.enabled=1 AND u.enabled=1 AND u.must_change=0
              ORDER BY u.username,b.name,b.id''')]

    def managed(self, token, workspace):
        with self.store.connect() as conn:
            self.store.require_session(conn, token, workspace=workspace)
            return [dict(r) for r in conn.execute('SELECT bidder_id,enabled FROM bidder_logins WHERE workspace_id=?',(workspace,))]

    def configure(self, token, workspace, bidder_id, name, *, password=None, enabled=True):
        if password is not None:self.store.validate_password(password)
        record = _record(password) if password is not None else None
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            actor=self.store.require_session(conn,token,workspace=workspace)
            if actor['must_change_password']:raise RevokedSession('Change your temporary password first.')
            if enabled:
                self._check_login_name(conn,name,workspace,bidder_id)
            existing=conn.execute('SELECT * FROM bidder_logins WHERE workspace_id=? AND bidder_id=?',(workspace,bidder_id)).fetchone()
            if enabled and not record and (not existing or not existing['hash']):
                raise ValueError('Set a password before enabling bidder access.')
            salt=record['salt'] if record else existing['salt'] if existing else None
            hashed=record['hash'] if record else existing['hash'] if existing else None
            conn.execute('''INSERT INTO bidder_logins(workspace_id,bidder_id,name,enabled,salt,hash,version,username_key)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id,bidder_id) DO UPDATE SET
              name=excluded.name,username_key=excluded.username_key,enabled=excluded.enabled,salt=excluded.salt,hash=excluded.hash,version=excluded.version''',
              (workspace,bidder_id,name,int(enabled),salt,hashed,secrets.token_hex(16),None if not enabled and name=='Removed bidder' else username_key(name)))
            conn.execute('DELETE FROM bidder_sessions WHERE login_id IN (SELECT id FROM bidder_logins WHERE workspace_id=? AND bidder_id=?)',(workspace,bidder_id))
            self.store.audit(conn,actor['user_id'],'bidder-access',f'{workspace}:{bidder_id}')

    @staticmethod
    def _check_login_name(conn,name,workspace,bidder_id):
        if conn.execute('''SELECT 1 FROM bidder_logins b JOIN users u ON u.workspace_id=b.workspace_id
            WHERE b.username_key=? AND u.removed_at IS NULL
            AND NOT (b.workspace_id=? AND b.bidder_id=?) LIMIT 1''',(username_key(name),workspace,bidder_id)).fetchone():
            raise ValueError('That bidder username is already in use. Choose another.')

    def rename(self, workspace, bidder_id, name):
        with self.store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._check_login_name(conn,name,workspace,bidder_id)
            conn.execute('UPDATE bidder_logins SET name=?,username_key=? WHERE workspace_id=? AND bidder_id=?',(name,username_key(name),workspace,bidder_id))

    def login(self, login_id, password, address):
        now=time.time()
        with self.store._lock:
            attempts=self.store._attempts
            for key in list(attempts):
                attempts[key]=[t for t in attempts[key] if t>now-60]
                if not attempts[key]:del attempts[key]
            recent=attempts.setdefault(address,[])
            if len(recent)>=10 or len(attempts)>10000:raise ValueError('Too many sign-in attempts. Try again in a minute.')
            recent.append(now)
        with self.store.connect() as conn:
            # Lookup is indexed and uses the same Unicode normalization as registration.
            # Existing conflicting names never select an arbitrary workspace.
            if isinstance(login_id,str):
                matches=conn.execute('''SELECT b.id FROM bidder_logins b
                  JOIN users u ON u.workspace_id=b.workspace_id
                  WHERE b.username_key=? AND u.removed_at IS NULL''',(username_key(login_id),)).fetchall()
                login_id=matches[0]['id'] if len(matches)==1 else None
            row=conn.execute('''SELECT b.*,u.version AS admin_version,u.owner,u.must_change,
              u.enabled AS admin_enabled,w.enabled AS workspace_enabled
              FROM bidder_logins b JOIN users u ON u.workspace_id=b.workspace_id
              JOIN workspaces w ON w.id=b.workspace_id WHERE b.id=?''',(login_id,)).fetchone()
            known=bool(row and row['enabled'] and row['admin_enabled'] and row['workspace_enabled'] and not row['must_change'])
            record=row if known and row['hash'] else self.store.dummy
            correct=hmac.compare_digest(_password(password,record['salt']),record['hash'])
            if not known or not correct:return None
            # Serialize the final check/session write against admin resets and access changes.
            conn.execute('BEGIN IMMEDIATE')
            current=conn.execute('SELECT version,enabled FROM bidder_logins WHERE id=?',(login_id,)).fetchone()
            admin=conn.execute('SELECT version,enabled,must_change FROM users WHERE workspace_id=?',(row['workspace_id'],)).fetchone()
            workspace=conn.execute('SELECT enabled FROM workspaces WHERE id=?',(row['workspace_id'],)).fetchone()
            if not current['enabled'] or current['version']!=row['version'] or not admin['enabled'] or admin['must_change'] or admin['version']!=row['admin_version'] or not workspace['enabled']:return None
            token=secrets.token_urlsafe(48)
            conn.execute('DELETE FROM bidder_sessions WHERE expires<=?',(now,))
            conn.execute('INSERT INTO bidder_sessions VALUES(?,?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),login_id,row['version'],row['admin_version'],self.store._owner_version() if row['owner'] else None,now+43200))
            self.store.audit(conn,None,'bidder-login',f"{row['workspace_id']}:{row['bidder_id']}")
        with self.store._lock:
            self.store._attempts.pop(address,None)
        return token

    def identity(self, token):
        if not token or len(token)>128:return None
        with self.store.connect() as conn:
            row=conn.execute('''SELECT s.*,b.version AS login_version,b.enabled,b.bidder_id,b.name,
              b.workspace_id,u.version AS current_admin_version,u.enabled AS admin_enabled,
              u.must_change,u.owner,u.username,w.name AS workspace_name,w.enabled AS workspace_enabled
              FROM bidder_sessions s JOIN bidder_logins b ON b.id=s.login_id
              JOIN users u ON u.workspace_id=b.workspace_id JOIN workspaces w ON w.id=b.workspace_id
              WHERE s.token_hash=?''',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not row or not row['enabled'] or not row['admin_enabled'] or not row['workspace_enabled'] or row['must_change'] or row['expires']<=time.time() or row['version']!=row['login_version'] or row['admin_version']!=row['current_admin_version']:return None
            if row['owner'] and row['owner_version']!=self.store._owner_version():return None
            return {'role':'bidder','bidder_id':row['bidder_id'],'bidder_name':row['name'],
                    'username':row['username'],'is_owner':False,'workspace_id':row['workspace_id'],
                    'workspace_name':row['workspace_name'],'must_change_password':False,'managed':True}

    def validate_dispatch(self, token, workspace):
        identity=self.identity(token)
        if not identity or identity['workspace_id']!=workspace:raise RevokedSession('Your bidder session changed. Sign in again.')
        return identity

    def logout(self, token):
        if token:
            with self.store.connect() as conn:
                conn.execute('DELETE FROM bidder_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
