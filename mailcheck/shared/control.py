"""Read-only use of the existing registry: no schema creation or migration."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

from ..control_store import ControlStore
from ..web.auth import AuthStore


class ControlReader(ControlStore):
    def __init__(self, root, legacy_paths):
        self.root = Path(root)
        self.path = self.root / 'control.db'
        self.legacy_auth = AuthStore(lambda: Path(legacy_paths[2]))
        self._lock = threading.RLock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
