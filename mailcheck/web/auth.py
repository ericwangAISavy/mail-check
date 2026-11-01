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

from ..maintenance import shared_writer

COOKIE = "mailcheck_session"
SESSION_SECONDS = 12 * 60 * 60
ROLES = ("admin", "bidder")
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

    @shared_writer
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

    @shared_writer
    def _load(self) -> dict:
        path = self.path()
        try:
            if not path.exists():
                self._save({"secret": secrets.token_hex(32),
                            "users": {"admin": _record("admin")}, "bidders": {}})
            data = json.loads(path.read_text())
            if len(bytes.fromhex(data["secret"])) != 32:
                raise ValueError("Invalid signing key")
            data.setdefault("bidders", {})
            for row in [data["users"]["admin"], *data["bidders"].values()]:
                if (len(bytes.fromhex(row["salt"])) != 16 or
                        len(bytes.fromhex(row["hash"])) != 32 or
                        not isinstance(row["version"], str) or not row["version"]):
                    raise ValueError("Invalid password record")
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AuthFileError("The local web-auth.json file cannot be read. Restore it from a trusted backup.") from exc

    @shared_writer
    def login(self, role: str, password: str, address: str, bidder_id: int | None = None) -> tuple[str | None, bool]:
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
            row = (data["bidders"].get(str(bidder_id)) if role == "bidder" else data["users"].get(role))
            known = row is not None
            row = row or data["users"]["admin"]
            matches = hmac.compare_digest(_password(password, row["salt"]), row["hash"])
            if role not in ROLES or not matches or not known:
                return None, False
            with self._attempt_lock:
                self._attempts.pop(address, None)
            return self._session(data, row, role, bidder_id), False

    @staticmethod
    def _session(data, row, role, bidder_id=None):
        payload = _encode(json.dumps({"role":role,"bidder_id":bidder_id if role=="bidder" else None,"version":row["version"],"expires":time.time()+SESSION_SECONDS,"nonce":secrets.token_hex(16)},separators=(",",":")).encode())
        signature = _encode(hmac.digest(bytes.fromhex(data["secret"]),payload.encode(),"sha256"))
        return f"{payload}.{signature}"

    @shared_writer
    def identity(self, token: str | None) -> dict | None:
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
                row = data["bidders"].get(str(value.get("bidder_id"))) if role == "bidder" else data["users"].get(role)
                if (role not in ROLES or not row or value["expires"] <= time.time() or
                        value["version"] != row["version"]):
                    return None
                return {"role": role, "bidder_id": value.get("bidder_id")}
            except (ValueError, KeyError, TypeError, UnicodeError):
                return None

    @shared_writer
    def change_password(self, role: str, password: str) -> None:
        if role != "admin" or not 1 <= len(password) <= 256:
            raise ValueError("Choose admin and a password of 1–256 characters.")
        with _file_lock:
            data = self._load()
            data["users"][role] = _record(password)
            self._save(data)

    def role(self, token: str | None) -> str | None:
        identity = self.identity(token)
        return identity["role"] if identity else None

    @shared_writer
    def set_bidder_password(self, bidder_id: int, password: str) -> None:
        if not 8 <= len(password) <= 256:
            raise ValueError("Choose a password of 8–256 characters.")
        with _file_lock:
            data = self._load()
            data["bidders"][str(bidder_id)] = _record(password)
            self._save(data)

    @shared_writer
    def change_bidder_password(self, bidder_id: int, current: str, password: str) -> str:
        with _file_lock:
            data = self._load()
            row = data["bidders"].get(str(bidder_id))
            if not row or not hmac.compare_digest(_password(current, row["salt"]), row["hash"]):
                raise ValueError("Current password is incorrect.")
            if not 8 <= len(password) <= 256: raise ValueError("Choose a password of 8–256 characters.")
            data["bidders"][str(bidder_id)] = _record(password)
            self._save(data)
            return self._session(data,data["bidders"][str(bidder_id)],"bidder",bidder_id)
