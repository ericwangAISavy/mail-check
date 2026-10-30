"""Serialized daily backups and local archive history for the owner gateway."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import hashlib
import time
import re
import secrets
import threading
import zipfile
from .backups import BackupError, create_archive, private_json

NAME=re.compile(r'(?:auto|manual)-\d{8}T\d{6}Z-[a-f0-9]{8}\.zip\Z')


def utcnow():return datetime.now(timezone.utc)


class BackupManager:
    def __init__(self,layout,registry_lock):
        self.layout=layout;self.registry_lock=registry_lock
        self.folder=layout.control/'backups'
        self.settings=self.folder/'settings.json'
        self._state_lock=threading.RLock();self._job_lock=threading.Lock();self.running=False
        self._tickets={}

    def _read(self):
        if not self.settings.exists():
            state={'enabled':True,'retain':7,'next_due':(utcnow()+timedelta(days=1)).isoformat(),'last_success':None,'last_error':None}
            private_json(self.settings,state)
            return state
        try:
            state=json.loads(self.settings.read_text(encoding='utf-8'))
            if not isinstance(state['enabled'],bool) or type(state['retain']) is not int or not 1<=state['retain']<=30:raise ValueError()
            if state.get('next_due') and datetime.fromisoformat(state['next_due']).tzinfo is None:raise ValueError()
            return state
        except (OSError,ValueError,TypeError,KeyError) as exc:raise BackupError('Backup settings could not be read. Existing archives were preserved.') from exc

    def status(self):
        with self._state_lock:state=self._read();running=self.running
        archives=[]
        for path in sorted(self.folder.glob('*.zip'),reverse=True):
            if not NAME.fullmatch(path.name) or path.is_symlink():continue
            try:
                with zipfile.ZipFile(path) as archive:
                    if archive.getinfo('manifest.json').file_size>2*1024*1024:continue
                    created=json.loads(archive.read('manifest.json'))['created_at']
                archives.append({'name':path.name,'size':path.stat().st_size,'created_at':created,'automatic':path.name.startswith('auto-')})
            except (OSError,ValueError,KeyError,zipfile.BadZipFile):continue
        return {**state,'folder':str(self.folder),'running':running,'archives':archives}

    def configure(self,enabled,retain):
        if not isinstance(enabled,bool) or type(retain) is not int or not 1<=retain<=30:raise BackupError('Choose 1–30 automatic backups.')
        with self._state_lock:
            state=self._read()
            if enabled and not state['enabled']:state['next_due']=(utcnow()+timedelta(days=1)).isoformat()
            if not enabled:state['next_due']=None
            state.update(enabled=enabled,retain=retain);private_json(self.settings,state)
        return self.status()

    def create(self,*,automatic=False):
        if not self._job_lock.acquire(blocking=False):raise BackupError('Another backup is already running.')
        with self._state_lock:self.running=True
        name=f'{"auto" if automatic else "manual"}-{utcnow():%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.zip'
        try:
            create_archive(self.layout,self.folder/name,_registry_lock=self.registry_lock)
            with self._state_lock:
                state=self._read();state['last_success']=utcnow().isoformat();state['last_error']=None
                if automatic and state['enabled']:state['next_due']=(utcnow()+timedelta(days=1)).isoformat()
                private_json(self.settings,state)
            if automatic:
                copies=[self.folder/name]+sorted([p for p in self.folder.glob('auto-*.zip') if p.name!=name and NAME.fullmatch(p.name) and not p.is_symlink()],key=lambda p:p.stat().st_mtime_ns,reverse=True)
                for path in copies[state['retain']:]:
                    try:path.unlink()
                    except OSError:pass  # A downloading file may be locked on Windows; retry next day.
            return {'ok':True,'name':name}
        except Exception as exc:
            with self._state_lock:
                state=self._read();state['last_error']=str(exc)
                if automatic and state['enabled']:state['next_due']=(utcnow()+timedelta(hours=1)).isoformat()
                private_json(self.settings,state)
            raise
        finally:
            with self._state_lock:self.running=False
            self._job_lock.release()

    def run_due(self):
        with self._state_lock:
            state=self._read()
            if not state['enabled'] or not state['next_due'] or datetime.fromisoformat(state['next_due'])>utcnow() or self.running:return
        self.create(automatic=True)

    def issue_ticket(self,name,session,workspace):
        self.download_path(name)
        token=secrets.token_urlsafe(32)
        with self._state_lock:
            now=time.monotonic()
            self._tickets={key:value for key,value in self._tickets.items() if value[3]>now}
            if len(self._tickets)>=256:raise BackupError('Too many pending downloads. Try again in a minute.')
            self._tickets[hashlib.sha256(token.encode()).hexdigest()]=(name,hashlib.sha256(session.encode()).hexdigest(),workspace,now+60)
        return token

    def consume_ticket(self,name,ticket,session,workspace):
        if not ticket or len(ticket)>128:raise BackupError('Download link expired. Start the download again.')
        key=hashlib.sha256(ticket.encode()).hexdigest()
        with self._state_lock:
            value=self._tickets.get(key)
            if not value or value[3]<=time.monotonic() or value[:3]!=(name,hashlib.sha256(session.encode()).hexdigest(),workspace):
                raise BackupError('Download link expired. Start the download again.')
            self._tickets.pop(key)
        return self.download_path(name)

    def download_path(self,name):
        if not NAME.fullmatch(name):raise BackupError('Backup not found.')
        path=self.folder/name
        if path.is_symlink() or not path.is_file():raise BackupError('Backup not found.')
        return path
