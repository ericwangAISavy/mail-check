"""Offline installation restore with durable rollback journal."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
from .backups import BackupLayout, BackupError, create_archive, inspect_archive, private_json, sqlite_check, durable_replace
from .maintenance import MaintenanceLock, journal_path


def _sync_directory(path):
    if os.name!='nt':
        fd=os.open(path,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def _remove(path):
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
    else:path.unlink(missing_ok=True)


def _targets(layout,stage):
    return [(layout.config,stage/'owner/config.toml'),(layout.database,stage/'owner/mailcheck.db'),
            (layout.auth,stage/'owner/web-auth.json'),(layout.config.parent/'credential-namespace',stage/'owner/credential-namespace'),
            (layout.control/'control.db',stage/'control/control.db'),(layout.control/'workspaces',stage/'workspaces'),
            *[(Path(str(path)+suffix),None) for path in (layout.database,layout.control/'control.db') for suffix in ('-wal','-shm')]]


def _rebase(stage,layout,manifest):
    token=secrets.token_hex(16)
    (stage/'owner/credential-namespace').write_text(token,encoding='ascii')
    for wid in [w['id'] for w in manifest['workspaces']]:
        root=stage/'workspaces'/wid
        (root/'config').mkdir(parents=True,exist_ok=True)
        (root/'config/credential-namespace').write_text(token,encoding='ascii')
    (stage/'workspaces').mkdir(exist_ok=True)
    for auth in [stage/'owner/web-auth.json',*(stage/'workspaces').glob('*/config/web-auth.json')]:
        if auth.exists():
            data=json.loads(auth.read_text(encoding='utf-8'));data['secret']=secrets.token_hex(32);private_json(auth,data)
    control=stage/'control/control.db'
    if control.exists():
        with closing(sqlite3.connect(control)) as conn:
            for workspace in manifest['workspaces']:
                conn.execute('UPDATE workspaces SET root=? WHERE id=?',(str((layout.control/'workspaces'/workspace['id']).resolve()),workspace['id']))
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('sessions','bidder_sessions'):
                if table in tables:conn.execute(f'DELETE FROM {table}')
            conn.commit()
        sqlite_check(control)


def _journal(layout):
    path=journal_path(layout.lock)
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('format')!=1 or data.get('state') not in ('prepared','committed'):raise ValueError()
        transaction=data['transaction']
        if len(transaction)!=32 or any(c not in '0123456789abcdef' for c in transaction):raise ValueError()
        allowed={str(p.absolute()) for p,_ in _targets(layout,Path('/unused'))}
        if len(data['entries'])!=len(allowed) or {entry['target'] for entry in data['entries']}!=allowed:raise ValueError()
        for entry in data['entries']:
            target=Path(entry['target'])
            for field,suffix in (('old','old'),('new','new')):
                if entry[field]!=str(target.with_name(f'.offerpath-{transaction}-{target.name}.{suffix}')):raise ValueError()
            if not isinstance(entry['had_old'],bool):raise ValueError()
        return path,data
    except (OSError,ValueError,TypeError,KeyError) as exc:raise BackupError('Restore journal is invalid. Preserve it and recover with the original destination paths.') from exc


def _recover_locked(layout):
    path,data=_journal(layout)
    for entry in reversed(data['entries']):
        target,old,new=map(Path,(entry['target'],entry['old'],entry['new']))
        if data['state']=='prepared':
            if old.exists():
                _remove(target);durable_replace(old,target)
            elif not entry['had_old']:_remove(target)
        _remove(new)
        if data['state']=='committed':_remove(old)
        _sync_directory(target.parent)
    path.unlink();_sync_directory(path.parent)
    return {'ok':True,'recovered':'previous installation' if data['state']=='prepared' else 'completed restore','rollback':data.get('rollback')}


def recover_restore(layout:BackupLayout):
    with MaintenanceLock(layout.lock,exclusive=True,allow_journal=True):
        if not journal_path(layout.lock).exists():raise BackupError('No interrupted restore needs recovery.')
        return _recover_locked(layout)


def restore_archive(archive:Path,layout:BackupLayout,*,replace=False):
    # Inspection occurs before locking or creating destination installation files.
    manifest=inspect_archive(archive)
    with MaintenanceLock(layout.lock,exclusive=True),tempfile.TemporaryDirectory(prefix='offerpath-restore-') as temporary:
        stage=Path(temporary);inspect_archive(archive,destination=stage)
        targets=_targets(layout,stage)
        paths=[str(target.absolute()) for target,_ in targets]
        if len(paths)!=len(set(paths)) or any(Path(a) in Path(b).parents for a in paths for b in paths if a!=b):raise BackupError('Destination paths overlap.')
        archive_path=Path(archive).resolve()
        if any(archive_path==Path(p).resolve() or Path(p).resolve() in archive_path.parents for p in paths):raise BackupError('Move the archive outside destination files before restoring.')
        for target,_ in targets:
            if target.is_symlink() or any(p.is_symlink() for p in target.parents):raise BackupError('Restore destinations cannot use symbolic links.')
        existing=any(target.exists() for target,_ in targets)
        if existing and not replace:raise BackupError('Destination contains data. Use --replace to create a rollback backup and replace it.')
        rollback=None
        if existing:
            folder=layout.config.parent/'offerpath-restore-rollbacks'
            folder.mkdir(mode=0o700,parents=True,exist_ok=True)
            rollback=folder/f'rollback-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.zip'
            create_archive(layout,rollback,_locked=True)
        _rebase(stage,layout,manifest)
        transaction=secrets.token_hex(16);entries=[]
        journal=journal_path(layout.lock)
        try:
            for target,source in targets:
                target=target.absolute();target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                old=target.with_name(f'.offerpath-{transaction}-{target.name}.old')
                new=target.with_name(f'.offerpath-{transaction}-{target.name}.new')
                entries.append({'target':str(target),'old':str(old),'new':str(new),'had_old':target.exists()})
                if source is not None and source.exists():
                    if source.is_dir():shutil.copytree(source,new)
                    else:shutil.copyfile(source,new);new.chmod(0o600)
                    for file in ([new] if new.is_file() else new.rglob('*')):
                        if file.is_file():
                            file.chmod(0o600)
                            with file.open('r+b') as stream:os.fsync(stream.fileno())
                    if new.is_dir():
                        for directory in sorted([new,*[p for p in new.rglob('*') if p.is_dir()]],key=lambda p:len(p.parts),reverse=True):
                            _sync_directory(directory)
                for parent in [target.parent,*target.parent.parents]:_sync_directory(parent)
            record={'format':1,'state':'prepared','transaction':transaction,'entries':entries,'rollback':str(rollback) if rollback else None}
            private_json(journal,record);_sync_directory(journal.parent)
            for entry in entries:
                target,old,new=map(Path,(entry['target'],entry['old'],entry['new']))
                if entry['had_old']:durable_replace(target,old)
                if new.exists():durable_replace(new,target)
                _sync_directory(target.parent)
            record['state']='committed';private_json(journal,record);_sync_directory(journal.parent)
            _recover_locked(layout)
        except BaseException:
            if journal.exists():_recover_locked(layout)
            else:
                for entry in entries:_remove(Path(entry['new']))
            raise
        return {'ok':True,'rollback':str(rollback) if rollback else None,'workspaces':len(manifest['workspaces']),
                'message':'Restore complete. Sign in again, reconnect Outlook/IMAP accounts, and verify model and network settings.'}
