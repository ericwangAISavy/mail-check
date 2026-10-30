"""Immutable per-process workspace boundaries and non-destructive legacy backup."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def workspace_root() -> Path | None:
    root=os.environ.get('OFFERPATH_WORKSPACE_ROOT')
    wid=os.environ.get('OFFERPATH_WORKSPACE_ID')
    if not root and not wid:return None
    if not root or not wid or not re.fullmatch('[a-f0-9]{32}',wid):
        raise ValueError('Invalid workspace configuration; refusing legacy fallback.')
    path=Path(root)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError('Workspace directory is unavailable; refusing legacy fallback.')
    if (path/'workspace.id').read_text().strip()!=wid:
        raise ValueError('Workspace identity mismatch.')
    return path


def credential_namespace() -> str:
    root=workspace_root()
    from .config import config_dir
    marker=(root/'config' if root else config_dir())/'credential-namespace'
    restored=''
    if marker.exists():
        token=marker.read_text(encoding='ascii').strip()
        if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('Restored credential namespace is invalid. Restore it from backup.')
        restored=f'restored:{token}:'
    return restored+(f"workspace:{os.environ['OFFERPATH_WORKSPACE_ID']}:" if root else '')


def provision(root: Path, wid: str) -> Path:
    if not re.fullmatch('[a-f0-9]{32}',wid):raise ValueError('Invalid workspace ID.')
    path=root/wid
    path.mkdir(mode=0o700,parents=True,exist_ok=False)
    (path/'config').mkdir(mode=0o700)
    (path/'data').mkdir(mode=0o700)
    (path/'workspace.id').write_text(wid)
    return path


def backup_legacy(destination: Path, config_file: Path, database: Path, auth_file: Path) -> Path:
    """Read the original files only; SQLite's online backup includes WAL data."""
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    manifest={}
    for name,path in [('config.toml',config_file),('web-auth.json',auth_file)]:
        if path.exists():
            content=path.read_bytes()
            with (destination/name).open('wb') as target:
                os.chmod(destination/name,0o600)
                target.write(content);target.flush();os.fsync(target.fileno())
            manifest[name]={'original':str(path),'sha256':hashlib.sha256(content).hexdigest()}
    if database.exists():
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(destination/'mailcheck.db') as target:
            source.backup(target)
        os.chmod(destination/'mailcheck.db',0o600)
        manifest['mailcheck.db']={'original':str(database),'backup_sha256':hashlib.sha256((destination/'mailcheck.db').read_bytes()).hexdigest()}
    with (destination/'manifest.json').open('w',encoding='utf-8') as target:
        json.dump(manifest,target,indent=2)
        target.flush();os.fsync(target.fileno())
    return destination
