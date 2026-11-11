"""Atomic local initialization. Re-running validates; it never rotates secrets."""
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from .settings import ROLES,read_secret
from .broker import build_definitions

TOPOLOGY_VERSION=1
NAMES=['postgres_admin_password']+[f'{role}_{kind}_password' for role in ROLES for kind in ('db','migration','broker')]


def initialize(root:Path):
    root=Path(root)
    if root.is_symlink() or getattr(root,'is_junction',lambda:False)():raise ValueError('Service state cannot be a link')
    if root.exists():
        try:
            manifest=root/'manifest.json'
            if manifest.is_symlink():raise ValueError
            data=json.loads(manifest.read_text())
            expected=set(NAMES+['rabbitmq_definitions'])
            if data['format']!=1 or data.get('topology_version',1)!=TOPOLOGY_VERSION or set(data['hashes'])!=expected:raise ValueError
            if os.name!='nt' and root.stat().st_mode & 0o077:raise ValueError
            folder=root/'secrets'
            if folder.is_symlink() or set(p.name for p in folder.iterdir())!=expected:raise ValueError
            for name in NAMES:read_secret(folder,name)
            for name,digest in data['hashes'].items():
                path=folder/name
                if path.is_symlink() or sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError
            return 'existing'
        except (OSError,ValueError,KeyError,TypeError):
            raise ValueError('Existing service state is incomplete or changed; no files were overwritten') from None
    root.parent.mkdir(parents=True,exist_ok=True)
    pending=Path(tempfile.mkdtemp(prefix='.offerpath-init-',dir=root.parent))
    try:
        folder=pending/'secrets';folder.mkdir(mode=0o700)
        for name in NAMES:
            path=folder/name
            with path.open('x',encoding='ascii') as stream:stream.write(secrets.token_urlsafe(32))
            path.chmod(0o600)
        definitions=folder/'rabbitmq_definitions'
        definitions.write_text(json.dumps(build_definitions(folder),sort_keys=True,indent=2))
        # Only salted hashes; the broker's different UID must read this mount.
        definitions.chmod(0o644)
        manifest=pending/'manifest.json'
        manifest.write_text(json.dumps({'format':1,'topology_version':TOPOLOGY_VERSION,'hashes':{p.name:sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}},indent=2))
        manifest.chmod(0o600)
        os.rename(pending,root)
        return 'created'
    finally:
        if pending.exists():shutil.rmtree(pending)
