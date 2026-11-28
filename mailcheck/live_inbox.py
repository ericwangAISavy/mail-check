"""Short-lived bidder Inbox demand; shared/throttled per workspace process."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import threading
import time

INTERVAL_SECONDS = 30
ACTIVE_SECONDS = 20


class LiveInbox:
    def __init__(self):
        self._lock = threading.Lock()
        self._seen: dict[int,float] = {}
        self._next = 0.0
        self._running = False
        self._last: str | None = None
        self._attempt: str | None = None
        self._last_ok: bool | None = None

    def heartbeat(self, bidder_id: int):
        with self._lock:self._seen[bidder_id] = time.monotonic()

    def active(self):
        now = time.monotonic()
        with self._lock:
            self._seen = {who:at for who,at in self._seen.items() if now-at <= ACTIVE_SECONDS}
            return set(self._seen)

    def due(self):
        active = self.active()
        with self._lock:return bool(active) and not self._running and time.monotonic() >= self._next

    def reserve(self):
        if not self.active():return False
        with self._lock:
            if self._running or time.monotonic() < self._next:return False
            self._running = True
            self._attempt = datetime.now(timezone.utc).isoformat()
            self._next = time.monotonic() + INTERVAL_SECONDS
            return True

    def finish(self, success=False):
        with self._lock:
            self._running = False
            self._last_ok = bool(success)
            self._next = max(self._next, time.monotonic() + (INTERVAL_SECONDS if success else 60))
            if success:self._last = datetime.now(timezone.utc).isoformat()

    def snapshot(self, enabled, disabled_reason=None):
        with self._lock:
            remaining = max(0,self._next-time.monotonic())
            return {'enabled':bool(enabled),'interval_seconds':INTERVAL_SECONDS,
                    'running':self._running,'last_checked_at':self._last,
                    'last_attempt_at':self._attempt,'last_check_ok':self._last_ok,
                    'disabled_reason':disabled_reason if not enabled else None,
                    'next_at':(datetime.now(timezone.utc)+timedelta(seconds=remaining)).isoformat() if enabled else None}
