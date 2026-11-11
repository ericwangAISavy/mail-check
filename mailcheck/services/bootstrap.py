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


_ERRORS={
 'state_link':('Service state contains a symbolic link or junction.','Use a real local state directory; existing files were preserved.'),
 'state_not_directory':('The service state path is not a directory.','Choose a directory path; the existing file was preserved.'),
 'state_manifest_missing':('Existing service state has no manifest.json.','Restore manifest.json from the same state backup. Do not delete or regenerate existing credentials.'),
 'state_manifest_invalid':('The service state manifest is invalid or unsupported.','Restore a matching state backup; existing files were preserved.'),
 'state_topology_mismatch':('The state was initialized for a different broker topology.','Use a supported topology upgrade; existing files were preserved.'),
 'state_permissions':('The service state directory is accessible to other users.','Restrict directory access to your user before trying again.'),
 'state_files_missing':('The service secret file set is incomplete or unexpected.','Restore the complete state backup; credentials were not regenerated.'),
 'state_secrets_invalid':('An existing service secret file has an invalid format.','Restore the original credential files from the same state backup.'),
 'state_files_changed':('Existing credential or broker definition files do not match the manifest.','Restore matching files and manifest from the same backup; no credentials were overwritten.'),
 'state_unreadable':('The existing service state could not be read safely.','Check directory access and restore any missing state files before trying again.'),
}


class InitializationError(ValueError):
    """Only fixed, nonsecret diagnostics may cross the management boundary."""
    def __init__(self,code):
        message,self.hint=_ERRORS[code]
        self.code=code
        super().__init__(message)


def _linked(path):
    return path.is_symlink() or getattr(path,'is_junction',lambda:False)()


def _validate_existing(root):
    try:
        manifest=root/'manifest.json'
        if _linked(manifest):raise InitializationError('state_link')
        if not manifest.exists():raise InitializationError('state_manifest_missing')
        try:data=json.loads(manifest.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):raise InitializationError('state_manifest_invalid') from None
        expected=set(NAMES+['rabbitmq_definitions'])
        if not isinstance(data,dict) or data.get('format')!=1 or not isinstance(data.get('hashes'),dict):
            raise InitializationError('state_manifest_invalid')
        if data.get('topology_version',1)!=TOPOLOGY_VERSION:raise InitializationError('state_topology_mismatch')
        if set(data['hashes'])!=expected:raise InitializationError('state_manifest_invalid')
        if os.name!='nt' and root.stat().st_mode & 0o077:raise InitializationError('state_permissions')
        folder=root/'secrets'
        if _linked(folder):raise InitializationError('state_link')
        if not folder.is_dir() or set(p.name for p in folder.iterdir())!=expected:
            raise InitializationError('state_files_missing')
        try:
            for name in NAMES:read_secret(folder,name)
        except ValueError:raise InitializationError('state_secrets_invalid') from None
        for name,digest in data['hashes'].items():
            path=folder/name
            if _linked(path):raise InitializationError('state_link')
            if sha256(path.read_bytes()).hexdigest()!=digest:raise InitializationError('state_files_changed')
        return 'existing'
    except OSError:raise InitializationError('state_unreadable') from None


def initialize(root:Path):
    root=Path(root)
    if _linked(root):raise InitializationError('state_link')
    if root.exists():
        if not root.is_dir():raise InitializationError('state_not_directory')
        try:
            # An empty scaffold is safe to initialize. rmdir refuses to remove
            # anything if files appear concurrently; populated state is validated.
            if next(root.iterdir(),None) is None:root.rmdir()
            else:return _validate_existing(root)
        except OSError:raise InitializationError('state_unreadable') from None
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
