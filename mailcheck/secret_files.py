"""DPAPI-encrypted secret files for Windows, used in place of Credential Manager.

Credential Manager has a small per-user capacity, and OAuth caches need several
chunked entries each, so many accounts exhaust it ("Not enough memory resources").
Each secret here is one file in the workspace's private config folder, encrypted
to the Windows user and bound by entropy to its namespaced key, and replaced
atomically. Backups never include these files.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path

from . import dpapi


def enabled() -> bool:
    return dpapi.available()


def folder(name: str) -> Path:
    from . import config
    return config.config_path().parent / name


def path_for(name: str, identity: str) -> Path:
    """File names are hashes, so labels and e-mail addresses never appear on disk."""
    return folder(name) / (hashlib.sha256(identity.encode()).hexdigest() + ".bin")


def read(path: Path, magic: bytes, entropy: bytes) -> str | None:
    """None when there is no file; "" when it exists but cannot be used."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    if not raw.startswith(magic):
        return ""
    try:
        return dpapi.unprotect(raw[len(magic):], entropy).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""  # corrupt, or encrypted for another user/key


def write(path: Path, magic: bytes, entropy: bytes, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = magic + dpapi.protect(text.encode("utf-8"), entropy)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        replace(temporary, path)  # atomic: readers see the old or new secret, never a torn one
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def replace(source: str, target: Path) -> None:
    """Antivirus or indexing can briefly open the target on Windows; retry those
    sharing violations instead of failing the save."""
    for attempt in range(20):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
