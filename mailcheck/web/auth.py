"""File-backed passwords and signed, expiring browser sessions. No auth database."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

COOKIE = "mailcheck_session"
SESSION_SECONDS = 12 * 60 * 60
ROLES = ("admin", "guest")
_file_lock = threading.RLock()


class AuthFileError(RuntimeError):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _password(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                          n=16384, r=8, p=1, dklen=32).hex()


def _record(password: str) -> dict:
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _password(password, salt),
            "version": secrets.token_hex(16)}


class AuthStore:
    def __init__(self, path: Callable[[], Path]):
        self.path = path
        self._attempt_lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def _save(self, data: dict) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".web-auth-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(name, path)  # mkstemp creates a private (0600) file.
        finally:
            Path(name).unlink(missing_ok=True)

    def _load(self) -> dict:
        path = self.path()
        try:
            if not path.exists():
                self._save({"secret": secrets.token_hex(32),
                            "users": {role: _record(role) for role in ROLES}})
            data = json.loads(path.read_text())
            if len(bytes.fromhex(data["secret"])) != 32:
                raise ValueError("Invalid signing key")
            for role in ROLES:
                row = data["users"][role]
                if (len(bytes.fromhex(row["salt"])) != 16 or
                        len(bytes.fromhex(row["hash"])) != 32 or
                        not isinstance(row["version"], str) or not row["version"]):
                    raise ValueError("Invalid password record")
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AuthFileError("The local web-auth.json file cannot be read. Restore it from a trusted backup.") from exc

    def login(self, role: str, password: str, address: str) -> tuple[str | None, bool]:
        now = time.time()
        with self._attempt_lock:
            # Bound retained entries and avoid trusting client-supplied forwarding headers.
            self._attempts = {key: [t for t in times if t > now - 60]
                              for key, times in self._attempts.items() if times and times[-1] > now - 60}
            attempts = self._attempts.setdefault(address, [])
            if len(attempts) >= 10 or len(self._attempts) > 10000:
                return None, True
            attempts.append(now)
        with _file_lock:
            data = self._load()
            row = data["users"].get(role, data["users"]["admin"])
            matches = hmac.compare_digest(_password(password, row["salt"]), row["hash"])
            if role not in ROLES or not matches:
                return None, False
            with self._attempt_lock:
                self._attempts.pop(address, None)
            payload = _encode(json.dumps({"role": role, "version": row["version"],
                                          "expires": now + SESSION_SECONDS,
                                          "nonce": secrets.token_hex(16)}, separators=(",", ":")).encode())
            signature = _encode(hmac.digest(bytes.fromhex(data["secret"]), payload.encode(), "sha256"))
            return f"{payload}.{signature}", False

    def role(self, token: str | None) -> str | None:
        if not token or len(token) > 2048:
            return None
        with _file_lock:
            data = self._load()
            try:
                payload, signature = token.split(".")
                expected = _encode(hmac.digest(bytes.fromhex(data["secret"]), payload.encode(), "sha256"))
                if not hmac.compare_digest(expected, signature):
                    return None
                value = json.loads(_decode(payload))
                role = value["role"]
                if (role not in ROLES or value["expires"] <= time.time() or
                        value["version"] != data["users"][role]["version"]):
                    return None
                return role
            except (ValueError, KeyError, TypeError, UnicodeError):
                return None

    def change_password(self, role: str, password: str) -> None:
        if role not in ROLES or not 1 <= len(password) <= 256:
            raise ValueError("Choose admin or guest and a password of 1–256 characters.")
        with _file_lock:
            data = self._load()
            data["users"][role] = _record(password)
            self._save(data)
