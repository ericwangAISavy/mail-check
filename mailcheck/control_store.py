"""Owner/admin identities and workspace registry, separate from business SQLite."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .maintenance import shared_writer, connect_database
from .web.auth import AuthStore, _password, _record
from .workspaces import provision

SCHEMA='''
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,root TEXT,enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,workspace_id TEXT NOT NULL REFERENCES workspaces(id),owner INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,salt TEXT,hash TEXT,version TEXT NOT NULL,must_change INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS one_owner ON users(owner) WHERE owner=1;
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),workspace_id TEXT NOT NULL REFERENCES workspaces(id),version TEXT NOT NULL,owner_version TEXT,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL NOT NULL,actor INTEGER,action TEXT NOT NULL,target TEXT NOT NULL);
'''


class RevokedSession(PermissionError):
    pass


class ControlStore:
    @shared_writer
    def __init__(self, root: Path, legacy_auth: AuthStore, max_workspaces=4):
        self.root=root.resolve()
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.path=self.root/'control.db'
        self.legacy_auth=legacy_auth
        self.max_workspaces=max_workspaces
        self._lock=threading.RLock()
        self._attempts={}
        self._presence={}  # Ephemeral browser activity; never business data.
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO workspaces VALUES('legacy','Original workspace',NULL,1)")
            conn.execute("INSERT OR IGNORE INTO users(id,username,workspace_id,owner,version,must_change) VALUES(1,'owner','legacy',1,?,0)",(secrets.token_hex(16),))
        self.path.chmod(0o600)
        self.dummy=_record(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        conn=connect_database(self.path,timeout=30)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:yield conn
        finally:conn.close()

    def audit(self,conn,actor,action,target):
        conn.execute('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)',(time.time(),actor,action,str(target)))

    def _owner_version(self):
        if not self.legacy_auth.path().is_file():
            from .web.auth import AuthFileError
            raise AuthFileError('Original owner authentication is unavailable.')
        return self.legacy_auth._load()['users']['admin']['version']

    def _identity(self,conn,row):
        workspace=conn.execute('SELECT * FROM workspaces WHERE id=?',(row['selected_workspace'],)).fetchone()
        user=conn.execute('SELECT * FROM users WHERE id=?',(row['user_id'],)).fetchone()
        if not user or not workspace or not user['enabled'] or not workspace['enabled'] or row['expires']<=time.time() or row['version']!=user['version']:return None
        if not user['owner'] and user['workspace_id']!=workspace['id']:return None
        if user['owner'] and row['owner_version']!=self._owner_version():return None
        return {'role':'admin','user_id':user['id'],'username':user['username'],'is_owner':bool(user['owner']),
                'workspace_id':workspace['id'],'workspace_name':workspace['name'],'must_change_password':bool(user['must_change'])}

    def identity(self,token):
        if not token or len(token)>128:return None
        with self.connect() as conn:
            row=conn.execute('SELECT *,workspace_id AS selected_workspace FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            return self._identity(conn,row) if row else None

    def require_session(self,conn,token,*,owner=False,workspace=None):
        # Call under BEGIN IMMEDIATE for mutations: a password reset/logout
        # cannot race between this validation and the protected write.
        row=None
        if isinstance(token,str) and len(token)<=128:
            row=conn.execute('SELECT *,workspace_id AS selected_workspace FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        identity=self._identity(conn,row) if row else None
        if not identity or workspace is not None and identity['workspace_id']!=workspace:
            raise RevokedSession('Your session changed. Sign in again.')
        if owner and not identity['is_owner']:raise PermissionError('Owner access required.')
        return identity

    def validate_dispatch(self,token,workspace):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            identity=self.require_session(conn,token,workspace=workspace)
            if identity['must_change_password']:raise RevokedSession('Change your temporary password before continuing.')
            return identity

    def _session(self,conn,user,workspace=None):
        token=secrets.token_urlsafe(48)
        conn.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],workspace or user['workspace_id'],user['version'],self._owner_version() if user['owner'] else None,time.time()+43200))
        return token

    def login(self,username,password,address):
        now=time.time()
        with self._lock:
            self._attempts={k:[t for t in v if t>now-60] for k,v in self._attempts.items() if v and v[-1]>now-60}
            attempts=self._attempts.setdefault(address,[])
            if len(attempts)>=10 or len(self._attempts)>10000:raise ValueError('Too many sign-in attempts. Try again in a minute.')
            attempts.append(now)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user=conn.execute('SELECT * FROM users WHERE username=?',(username.strip().casefold(),)).fetchone()
            known=bool(user and user['enabled'])
            if known and user['owner']:
                self._owner_version()
                token,limited=self.legacy_auth.login('admin',password,address)
                correct=bool(token)
            else:
                record=user if known and user['hash'] else self.dummy
                correct=hmac.compare_digest(_password(password,record['salt']),record['hash'])
            workspace=conn.execute('SELECT enabled FROM workspaces WHERE id=?',(user['workspace_id'],)).fetchone() if user else None
            if not known or not correct or not workspace or not workspace['enabled']:return None
            token=self._session(conn,user)
            self.audit(conn,user['id'],'login',user['workspace_id'])
        with self._lock:self._attempts.pop(address,None)
        return token

    def logout(self,token):
        if token:
            with self.connect() as conn:conn.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
            with self._lock:self._presence.pop(hashlib.sha256(token.encode()).hexdigest(),None)

    def record_presence(self,token):
        if not self.identity(token):raise RevokedSession('Sign in to continue.')
        key=hashlib.sha256(token.encode()).hexdigest()
        with self._lock:self._presence[key]=time.monotonic()

    def online_admin_ids(self):
        now=time.monotonic()
        with self._lock:
            self._presence={key:seen for key,seen in self._presence.items() if 0<=now-seen<90}
            active=set(self._presence)
        if not active:return set()
        online=set()
        with self.connect() as conn:
            rows=conn.execute('SELECT *,workspace_id AS selected_workspace FROM sessions WHERE expires>?',(time.time(),)).fetchall()
            for row in rows:
                if row['token_hash'] in active and self._identity(conn,row):online.add(row['user_id'])
        return online

    def list_admins(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT u.id,u.username,u.owner,u.enabled,u.must_change,w.id AS workspace_id,w.name AS workspace_name FROM users u JOIN workspaces w ON w.id=u.workspace_id ORDER BY u.owner DESC,u.username')]

    def workspace(self,wid):
        with self.connect() as conn:
            row=conn.execute('SELECT * FROM workspaces WHERE id=? AND enabled=1',(wid,)).fetchone()
            if not row:raise ValueError('Workspace is disabled or unavailable.')
            return dict(row)

    def enabled_workspaces(self):
        with self.connect() as conn:return [dict(r) for r in conn.execute('SELECT * FROM workspaces WHERE enabled=1')]

    def create_admin(self,token,username,name,password,*,expected_workspace=None):
        username=username.strip().casefold()
        if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,63}',username) or username in ('owner','admin'):raise ValueError('Choose a unique username of 3–64 letters, digits, dots, underscores or hyphens; start with a letter.')
        if not name.strip() or len(name)>100:raise ValueError('Enter a workspace name of 1–100 characters.')
        self.validate_password(password)
        record=_record(password)
        with self._lock,self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            actor=self.require_session(conn,token,owner=True,workspace=expected_workspace)['user_id']
            if conn.execute('SELECT COUNT(*) FROM workspaces WHERE enabled=1').fetchone()[0]>=self.max_workspaces:raise ValueError('Workspace capacity reached. Increase --max-workspaces or suspend another workspace.')
            if conn.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():raise ValueError('That username is already in use.')
            wid=secrets.token_hex(16)
            path=provision(self.root/'workspaces',wid)
            conn.execute('INSERT INTO workspaces VALUES(?,?,?,1)',(wid,name.strip(),str(path)))
            cur=conn.execute('INSERT INTO users(username,workspace_id,salt,hash,version) VALUES(?,?,?,?,?)',(username,wid,record['salt'],record['hash'],record['version']))
            self.audit(conn,actor,'create-admin',cur.lastrowid)
            return wid

    @staticmethod
    def validate_password(password):
        if not 12<=len(password)<=256:raise ValueError('Use a password of 12–256 characters.')

    def update_admin(self,token,user_id,*,enabled=None,password=None,expected_workspace=None):
        if password is not None:self.validate_password(password)
        with self._lock,self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            actor=self.require_session(conn,token,owner=True,workspace=expected_workspace)['user_id']
            user=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not user or user['owner']:raise ValueError('The owner cannot be reset or disabled here.')
            if enabled is True and not user['enabled'] and conn.execute('SELECT COUNT(*) FROM workspaces WHERE enabled=1').fetchone()[0]>=self.max_workspaces:raise ValueError('Workspace capacity reached.')
            if enabled is not None:
                conn.execute('UPDATE users SET enabled=?,version=? WHERE id=?',(int(enabled),secrets.token_hex(16),user_id))
                conn.execute('UPDATE workspaces SET enabled=? WHERE id=?',(int(enabled),user['workspace_id']))
            if password is not None:
                record=_record(password)
                conn.execute('UPDATE users SET salt=?,hash=?,version=?,must_change=1 WHERE id=?',(record['salt'],record['hash'],record['version'],user_id))
            conn.execute('DELETE FROM sessions WHERE user_id=? OR workspace_id=?',(user_id,user['workspace_id']))
            self.audit(conn,actor,'update-admin',user_id)
            return user['workspace_id']

    def change_password(self,token,password,*,expected_workspace=None):
        self.validate_password(password)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            identity=self.require_session(conn,token,workspace=expected_workspace)
            if identity['is_owner']:self.legacy_auth.change_password('admin',password)
            record=_record(password)
            conn.execute('UPDATE users SET salt=?,hash=?,version=?,must_change=0 WHERE id=?',(record['salt'],record['hash'],record['version'],identity['user_id']))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(identity['user_id'],))
            self.audit(conn,identity['user_id'],'change-password',identity['user_id'])
            user=conn.execute('SELECT * FROM users WHERE id=?',(identity['user_id'],)).fetchone()
            return self._session(conn,user,identity['workspace_id'])

    def switch(self,token,wid,*,expected_workspace=None):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            identity=self.require_session(conn,token,owner=True,workspace=expected_workspace)
            workspace=conn.execute('SELECT * FROM workspaces WHERE id=? AND enabled=1',(wid,)).fetchone()
            if not workspace:raise ValueError('Workspace is disabled or unavailable.')
            user=conn.execute('SELECT * FROM users WHERE id=?',(identity['user_id'],)).fetchone()
            self.audit(conn,user['id'],'switch-workspace',wid)
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
            return self._session(conn,user,wid)
