"""In-memory, per-minute gateway traffic counters for owner monitoring.

Constant memory (one small row per minute, 24 hours), O(1) per request, and no
paths, users or bodies are kept: only counts and a coarse latency histogram.
"""
from __future__ import annotations

import threading
import time

RETENTION_MINUTES = 24 * 60
# Upper bounds (ms) of the latency histogram; the last bin is open-ended.
LATENCY_BOUNDS_MS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
BINS = len(LATENCY_BOUNDS_MS) + 1
# Row layout: requests, client errors (4xx), server errors (5xx), throttled
# (429/503), then the latency bins.
REQUESTS, CLIENT, SERVER, THROTTLED, LATENCY = 0, 1, 2, 3, 4
# Long-lived streams would only add their connection lifetime as "latency".
STREAM_PATHS = ('/api/realtime/events',)


def latency_bin(ms: float) -> int:
    for index, bound in enumerate(LATENCY_BOUNDS_MS):
        if ms <= bound:
            return index
    return BINS - 1


def percentile(histogram, q: float):
    """Estimate a percentile (ms) by linear interpolation inside its bin."""
    total = sum(histogram)
    if not total:
        return None
    rank, seen = q * total, 0
    for index, count in enumerate(histogram):
        if count and seen + count >= rank:
            low = 0 if index == 0 else LATENCY_BOUNDS_MS[index - 1]
            high = LATENCY_BOUNDS_MS[index] if index < len(LATENCY_BOUNDS_MS) else LATENCY_BOUNDS_MS[-1] * 2
            return round(low + (high - low) * ((rank - seen) / count), 1)
        seen += count
    return float(LATENCY_BOUNDS_MS[-1] * 2)


class TrafficMetrics:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: dict[int, list[int]] = {}

    def record(self, status: int, seconds: float | None) -> None:
        minute = int(self._clock() // 60)
        with self._lock:
            row = self._rows.get(minute)
            if row is None:
                row = self._rows[minute] = [0] * (LATENCY + BINS)
                if len(self._rows) > RETENTION_MINUTES:
                    cutoff = minute - RETENTION_MINUTES
                    for key in [key for key in self._rows if key <= cutoff]:
                        del self._rows[key]
            row[REQUESTS] += 1
            if 400 <= status < 500:
                row[CLIENT] += 1
            elif status >= 500:
                row[SERVER] += 1
            if status in (429, 503):
                row[THROTTLED] += 1
            if seconds is not None:
                row[LATENCY + latency_bin(seconds * 1000)] += 1

    def rows(self, since_minute: int) -> dict[int, list[int]]:
        with self._lock:
            return {minute: list(row) for minute, row in self._rows.items() if minute >= since_minute}


class TrafficMiddleware:
    """Pure ASGI wrapper: times each request to its response headers."""

    def __init__(self, app, metrics: TrafficMetrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '') if scope['type'] == 'http' else ''
        # Static files and worker control traffic are not user traffic.
        if scope['type'] != 'http' or path.startswith(('/assets/', '/static/', '/_internal/')):
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = {'code': None}
        timed = not path.startswith(STREAM_PATHS)

        async def tracked_send(message):
            if message['type'] == 'http.response.start' and status['code'] is None:
                status['code'] = int(message.get('status', 500))
                self.metrics.record(status['code'], time.perf_counter() - started if timed else None)
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except BaseException:
            if status['code'] is None:
                self.metrics.record(500, time.perf_counter() - started if timed else None)
            raise
