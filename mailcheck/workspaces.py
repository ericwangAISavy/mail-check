"""Immutable per-process workspace boundaries and non-destructive legacy backup."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
import threading
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    root: Path | None
    legacy_config: Path
    legacy_db: Path
    control_root: Path
    shared_config: Path | None = None

    @classmethod
    def from_record(cls, record, legacy_paths, control_root):
        wid = record['id']
        legacy_config, legacy_db = map(Path, legacy_paths[:2])
        if wid == 'legacy':
            if record['root'] is not None:
                raise ValueError('Invalid legacy workspace root.')
            root = None
        else:
            root = Path(record['root']) if record['root'] else None
            if not re.fullmatch('[a-f0-9]{32}', wid) or root is None:
                raise ValueError('Invalid workspace record; refusing legacy fallback.')
            _validate_root(root, wid)
        return cls(wid, root, legacy_config, legacy_db, Path(control_root),
                   legacy_config if root else None)


_workspace = ContextVar('mailcheck_workspace', default=None)
_commit_guard = ContextVar('mailcheck_commit_guard', default=None)


def current_workspace():
    return _workspace.get()


@contextmanager
def bind_workspace(context):
    token = _workspace.set(context)
    try:
        yield context
    finally:
        _workspace.reset(token)


def current_commit_guard():
    return _commit_guard.get()


@contextmanager
def bind_commit_guard(check):
    token = _commit_guard.set(check)
    try:
        yield
    finally:
        _commit_guard.reset(token)


def start_workspace_thread(target, **kwargs):
    context = copy_context()
    args = kwargs.pop('args', ())
    target_kwargs = kwargs.pop('kwargs', {})
    thread = threading.Thread(target=lambda: context.run(target, *args, **target_kwargs), **kwargs)
    thread.start()
    return thread


def _validate_root(path, wid):
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError('Workspace directory is unavailable; refusing legacy fallback.')
    if (path/'workspace.id').read_text().strip() != wid:
        raise ValueError('Workspace identity mismatch.')


def workspace_root() -> Path | None:
    context = current_workspace()
    if context is not None:
        if context.root is not None:
            _validate_root(context.root, context.workspace_id)
        return context.root
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
    return restored+(f"workspace:{current_workspace().workspace_id if current_workspace() else os.environ['OFFERPATH_WORKSPACE_ID']}:" if root else '')


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
