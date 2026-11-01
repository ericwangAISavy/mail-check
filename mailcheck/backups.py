"""Portable, plain ZIP installation snapshots. Never exports OS keyring secrets."""
from __future__ import annotations
from contextlib import nullcontext, closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import tomllib
import zipfile

from . import __version__
from .maintenance import MaintenanceLock, lock_path

FORMAT=1
MAX_FILES=10000
MAX_EXPANDED=32*1024**3
MAX_FILE=16*1024**3
ID=re.compile(r'[a-f0-9]{32}\Z')

class BackupError(ValueError):
    pass

@dataclass(frozen=True)
class BackupLayout:
    config: Path
    database: Path
    control: Path

    @classmethod
    def current(cls):
        from . import config
        return cls(config.config_path(),config.db_path(),config.control_dir())

    @property
    def auth(self):return self.config.parent/'web-auth.json'

    @property
    def lock(self):return lock_path(self.config)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def durable_replace(source,target):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        move=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
        move.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD]
        move.restype=wintypes.BOOL
        if not move(str(source),str(target),1|8):raise ctypes.WinError(ctypes.get_last_error())
    else:os.replace(source,target)


def private_json(path,data):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as target:
            json.dump(data,target,indent=2);target.flush();os.fsync(target.fileno())
        durable_replace(name,path)
    finally:Path(name).unlink(missing_ok=True)


def sqlite_check(path):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            if conn.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise BackupError('A database failed its integrity check.')
    except sqlite3.Error as exc:raise BackupError('A database is unreadable or corrupt.') from exc


def _copy(source,target,database=False):
    source=Path(source)
    if source.is_symlink() or not source.is_file():raise BackupError(f'Required file is unavailable: {source.name}')
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if database:
        try:
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:
                src.backup(dst,pages=256,sleep=.01)
            sqlite_check(target)
        except sqlite3.Error as exc:raise BackupError(f'Could not snapshot {source.name}.') from exc
    else:shutil.copyfile(source,target)
    target.chmod(0o600)


def create_archive(layout:BackupLayout,output:Path,*,_locked=False,_registry_lock=None):
    """Snapshot independently consistent databases, including committed WAL data."""
    output=Path(output)
    if output.exists():raise BackupError('Backup output already exists.')
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (nullcontext() if _locked else MaintenanceLock(layout.lock)),tempfile.TemporaryDirectory(prefix='offerpath-backup-') as directory:
        stage=Path(directory);files={};workspaces=[]
        def add(name,source,kind='file',required=False):
            if not Path(source).exists() and not required:return
            target=stage/name;_copy(source,target,kind=='sqlite')
            files[name]={'kind':kind,'size':target.stat().st_size,'sha256':digest(target)}
        with (_registry_lock if _registry_lock is not None else nullcontext()):
            add('owner/config.toml',layout.config)
            add('owner/mailcheck.db',layout.database,'sqlite')
            add('owner/web-auth.json',layout.auth,required=True)
            control=layout.control/'control.db'
            if control.exists():
                add('control/control.db',control,'sqlite')
                with closing(sqlite3.connect(stage/'control/control.db')) as conn:
                    conn.row_factory=sqlite3.Row
                    for row in conn.execute("SELECT id,name,root,enabled FROM workspaces WHERE id!='legacy' ORDER BY id"):
                        wid=row['id']
                        if not ID.fullmatch(wid):raise BackupError('Invalid workspace identity in registry.')
                        root=Path(row['root'] or '')
                        if not root.is_absolute() or root.is_symlink() or not root.is_dir():raise BackupError(f'Workspace {wid} is unavailable.')
                        marker=root/'workspace.id'
                        if not marker.is_file() or marker.is_symlink() or marker.read_text().strip()!=wid:raise BackupError('Workspace identity does not match its registry.')
                        workspaces.append({'id':wid,'name':row['name'],'enabled':bool(row['enabled'])})
                        prefix=f'workspaces/{wid}'
                        add(prefix+'/workspace.id',marker,required=True)
                        add(prefix+'/config/config.toml',root/'config/config.toml')
                        add(prefix+'/config/web-auth.json',root/'config/web-auth.json')
                        add(prefix+'/data/mailcheck.db',root/'data/mailcheck.db','sqlite')
        manifest={'format':FORMAT,'app_version':__version__,'created_at':datetime.now(timezone.utc).isoformat(),
                  'workspaces':workspaces,'files':files,'credentials_included':False}
        private_json(stage/'manifest.json',manifest)
        fd,name=tempfile.mkstemp(prefix='.offerpath-',suffix='.zip',dir=output.parent);os.close(fd)
        temporary=Path(name)
        try:
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as archive:
                for item in ['manifest.json',*files]:archive.write(stage/item,item)
            inspect_archive(temporary)
            with temporary.open('r+b') as stream:os.fsync(stream.fileno())
            durable_replace(temporary,output);output.chmod(0o600)
        except (OSError,sqlite3.Error,zipfile.BadZipFile) as exc:raise BackupError('Backup creation failed; previous backups were preserved.') from exc
        finally:temporary.unlink(missing_ok=True)
        return manifest


def _safe_name(name):
    path=PurePosixPath(name)
    return bool(name and not name.endswith('/') and '\\' not in name and ':' not in name and not path.is_absolute()
                and all(part not in ('','..','.') for part in name.split('/')))


def inspect_archive(archive:Path,*,destination:Path|None=None):
    """Fully validate before exposing staged files to restore. No extractall."""
    try:
        with tempfile.TemporaryDirectory(prefix='offerpath-inspect-') as temporary:
            stage=Path(temporary)
            with zipfile.ZipFile(archive) as z:
                entries=z.infolist()
                if len(entries)>MAX_FILES or sum(i.file_size for i in entries)>MAX_EXPANDED:raise BackupError('Backup expansion limit exceeded.')
                names=[i.filename for i in entries]
                if len(names)!=len(set(names)) or len(names)!=len({n.casefold() for n in names}):raise BackupError('Duplicate backup paths.')
                for item in entries:
                    if not _safe_name(item.filename) or stat.S_ISLNK(item.external_attr>>16) or item.file_size>MAX_FILE or item.flag_bits&1:
                        raise BackupError('Unsafe or unsupported backup entry.')
                if 'manifest.json' not in names or z.getinfo('manifest.json').file_size>2*1024*1024:raise BackupError('Backup manifest is missing or too large.')
                manifest=json.loads(z.read('manifest.json'))
                if not isinstance(manifest,dict):raise BackupError('Invalid backup manifest.')
                if manifest.get('format')!=FORMAT or manifest.get('app_version')!=__version__:raise BackupError(f'Install OfferPath {manifest.get("app_version","unknown")} before restoring this backup (format must be {FORMAT}).')
                files=manifest.get('files');workspaces=manifest.get('workspaces')
                if not isinstance(files,dict) or not isinstance(workspaces,list) or len(workspaces)>1000:raise BackupError('Invalid backup inventory.')
                ids=[w.get('id') for w in workspaces if isinstance(w,dict)]
                if len(ids)!=len(workspaces) or len(ids)!=len(set(ids)) or any(not isinstance(wid,str) or not ID.fullmatch(wid) for wid in ids):raise BackupError('Invalid workspace inventory.')
                allowed={'owner/config.toml','owner/mailcheck.db','owner/web-auth.json','control/control.db'}
                for wid in ids:
                    allowed.update(f'workspaces/{wid}/{suffix}' for suffix in ('workspace.id','config/config.toml','config/web-auth.json','data/mailcheck.db'))
                    if f'workspaces/{wid}/workspace.id' not in files:raise BackupError('Workspace identity file is missing.')
                if 'owner/web-auth.json' not in files or (ids and 'control/control.db' not in files) or not set(files)<=allowed or set(names)!=set(files)|{'manifest.json'}:raise BackupError('Backup inventory does not match its files.')
                for name,record in files.items():
                    if not isinstance(record,dict) or record.get('kind') not in ('file','sqlite') or record.get('size')!=z.getinfo(name).file_size:raise BackupError('Invalid backup file metadata.')
                    path=stage/name;path.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(name) as src,path.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
                    path.chmod(0o600)
                    if digest(path)!=record.get('sha256'):raise BackupError('Backup checksum does not match.')
                    if name.endswith('.db'):
                        if record['kind']!='sqlite':raise BackupError('Invalid database metadata.')
                        sqlite_check(path)
                    if name.endswith('.toml'):
                        from .config import Config
                        Config.model_validate(tomllib.loads(path.read_text(encoding='utf-8')))
                    if name.endswith('web-auth.json'):
                        auth=json.loads(path.read_text(encoding='utf-8'))
                        if len(bytes.fromhex(auth['secret']))!=32:raise BackupError('Invalid sign-in configuration.')
                        for user in [auth['users']['admin'],*auth.get('bidders',{}).values()]:
                            if len(bytes.fromhex(user['salt']))!=16 or len(bytes.fromhex(user['hash']))!=32 or not user.get('version'):
                                raise BackupError('Invalid password record.')
                if 'control/control.db' in files:
                    with closing(sqlite3.connect(stage/'control/control.db')) as conn:
                        registered={r[0] for r in conn.execute("SELECT id FROM workspaces WHERE id!='legacy'")}
                    if registered!=set(ids):raise BackupError('Workspace registry and manifest differ.')
                for wid in ids:
                    if (stage/f'workspaces/{wid}/workspace.id').read_text().strip()!=wid:raise BackupError('Workspace marker mismatch.')
                if destination is not None:
                    destination=Path(destination)
                    for name in files:
                        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stage/name,target);target.chmod(0o600)
                return manifest
    except BackupError:raise
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,zipfile.BadZipFile,RuntimeError) as exc:
        raise BackupError('Backup is invalid, incomplete, or unreadable.') from exc
