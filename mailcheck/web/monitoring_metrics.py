"""Time series for the owner monitoring graphs: traffic, jobs and queue depth.

Everything is bounded: 24 hours of per-minute rows, fixed point counts per
range, and only counts (never paths, users, payloads or error text).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .traffic_metrics import CLIENT, LATENCY, REQUESTS, SERVER, THROTTLED, BINS, percentile as latency_percentile

# range -> (bucket seconds, bucket count)
RANGES = {'1h': (60, 60), '6h': (300, 72), '24h': (900, 96)}
STAGES = ('mail', 'calendar', 'classify')
JOB_ACTIONS = ('queued', 'started', 'completed', 'retry_or_failed', 'discarded')
OTHER = 'other'
DURATION_BOUNDS = (1, 2, 5, 10, 30, 60, 120, 300, 600)
METRICS_FILE_LIMIT = 4 * 1024 * 1024
QUEUE_SAMPLE_SECONDS = 60


def duration_percentile(histogram, q):
    """Seconds, interpolated inside the matching duration bin."""
    total = sum(histogram)
    if not total:
        return None
    rank, seen = q * total, 0
    for index, count in enumerate(histogram):
        if count and seen + count >= rank:
            low = 0 if index == 0 else DURATION_BOUNDS[index - 1]
            high = DURATION_BOUNDS[index] if index < len(DURATION_BOUNDS) else DURATION_BOUNDS[-1] * 2
            return round(low + (high - low) * ((rank - seen) / count), 1)
        seen += count
    return float(DURATION_BOUNDS[-1] * 2)


def read_job_minutes(path: Path, since_minute: int) -> dict[int, dict]:
    """Untrusted shared file: accept only known stages/actions and integer counts."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(METRICS_FILE_LIMIT + 1)
        if len(raw) > METRICS_FILE_LIMIT:
            return {}
        minutes = json.loads(raw).get('minutes')
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(minutes, dict):
        return {}
    result = {}
    for key, kinds in minutes.items():
        if not isinstance(key, str) or not key.isdigit() or int(key) < since_minute or not isinstance(kinds, dict):
            continue
        clean = {}
        for kind, row in kinds.items():
            if not isinstance(kind, str) or not isinstance(row, dict) or kind == 'events':
                continue
            stage = kind if kind in STAGES else OTHER
            target = clean.setdefault(stage, dict.fromkeys(JOB_ACTIONS, 0) | {'duration': [0] * (len(DURATION_BOUNDS) + 1)})
            for action in JOB_ACTIONS:
                value = row.get(action, 0)
                if type(value) is int and 0 <= value < 10**9:
                    target[action] += value
            histogram = row.get('duration')
            if isinstance(histogram, list) and len(histogram) == len(target['duration']) and all(type(v) is int and v >= 0 for v in histogram):
                target['duration'] = [a + b for a, b in zip(target['duration'], histogram)]
        if clean:
            result[int(key)] = clean
    return result


class QueueHistory:
    """Per-minute maximum queue depth, from monitoring snapshots."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: dict[int, dict[str, list[int]]] = {}

    def record(self, queues) -> None:
        minute = int(self._clock() // 60)
        with self._lock:
            row = self._rows.setdefault(minute, {})
            for queue in queues:
                kind = queue.get('kind')
                values = [queue.get('pending'), queue.get('retry'), queue.get('dead')]
                if not isinstance(kind, str) or not all(type(v) is int and v >= 0 for v in values):
                    continue
                previous = row.get(kind)
                row[kind] = values if previous is None else [max(a, b) for a, b in zip(previous, values)]
            cutoff = minute - 24 * 60
            for key in [key for key in self._rows if key <= cutoff]:
                del self._rows[key]

    def rows(self, since_minute: int):
        with self._lock:
            return {minute: {kind: list(v) for kind, v in row.items()} for minute, row in self._rows.items() if minute >= since_minute}


def build_series(range_key, traffic_rows, job_rows, queue_rows, now=None, jobs_tracked=True):
    step, count = RANGES[range_key]
    now = time.time() if now is None else now
    end = int(now // step) * step + step          # exclusive end of the current bucket
    start = end - step * count
    starts = [start + step * i for i in range(count)]

    def bucket(minute):
        index = (minute * 60 - start) // step
        return int(index) if 0 <= index < count else None

    requests = [0] * count; client = [0] * count; server = [0] * count; throttled = [0] * count
    latency = [[0] * BINS for _ in range(count)]
    total_latency = [0] * BINS
    for minute, row in traffic_rows.items():
        index = bucket(minute)
        if index is None:
            continue
        requests[index] += row[REQUESTS]; client[index] += row[CLIENT]
        server[index] += row[SERVER]; throttled[index] += row[THROTTLED]
        for b in range(BINS):
            latency[index][b] += row[LATENCY + b]
            total_latency[b] += row[LATENCY + b]

    stages = [*STAGES, OTHER]
    jobs = {stage: {action: [0] * count for action in JOB_ACTIONS} for stage in stages}
    durations = {stage: [[0] * (len(DURATION_BOUNDS) + 1) for _ in range(count)] for stage in stages}
    stage_duration = {stage: [0] * (len(DURATION_BOUNDS) + 1) for stage in stages}
    for minute, kinds in job_rows.items():
        index = bucket(minute)
        if index is None:
            continue
        for stage, row in kinds.items():
            for action in JOB_ACTIONS:
                jobs[stage][action][index] += row[action]
            durations[stage][index] = [a + b for a, b in zip(durations[stage][index], row['duration'])]
            stage_duration[stage] = [a + b for a, b in zip(stage_duration[stage], row['duration'])]

    # None marks buckets with no sample, so charts show a gap instead of a fake zero.
    ready = [None] * count; retry = [None] * count; dead = [None] * count
    for minute, row in queue_rows.items():
        index = bucket(minute)
        if index is None or not row:
            continue
        totals = [sum(values[i] for values in row.values()) for i in range(3)]
        for series, value in zip((ready, retry, dead), totals):
            series[index] = value if series[index] is None else max(series[index], value)

    all_requests, all_server, all_client = sum(requests), sum(server), sum(client)
    stage_totals = []
    for stage in stages:
        totals = {action: sum(jobs[stage][action]) for action in JOB_ACTIONS}
        finished = totals['completed'] + totals['retry_or_failed'] + totals['discarded']
        if stage == OTHER and not finished and not totals['queued']:
            continue
        stage_totals.append(dict(stage=stage, **totals,
            failure_rate=round((totals['retry_or_failed'] + totals['discarded']) / finished, 4) if finished else None,
            duration_p50=duration_percentile(stage_duration[stage], .5),
            duration_p95=duration_percentile(stage_duration[stage], .95)))
    completed = sum(sum(jobs[s]['completed']) for s in stages)
    failed = sum(sum(jobs[s]['retry_or_failed']) for s in stages)
    discarded = sum(sum(jobs[s]['discarded']) for s in stages)
    return dict(
        range=range_key, step=step, start=start, end=end, generated_at=now, buckets=starts, jobs_tracked=jobs_tracked,
        traffic=dict(requests=requests, client_errors=client, server_errors=server, throttled=throttled,
                     p50=[latency_percentile(h, .5) for h in latency], p95=[latency_percentile(h, .95) for h in latency]),
        jobs=dict(completed=[sum(jobs[s]['completed'][i] for s in stages) for i in range(count)],
                  failed=[sum(jobs[s]['retry_or_failed'][i] for s in stages) for i in range(count)],
                  discarded=[sum(jobs[s]['discarded'][i] for s in stages) for i in range(count)],
                  queued=[sum(jobs[s]['queued'][i] for s in stages) for i in range(count)],
                  stages={s: {a: jobs[s][a] for a in ('completed', 'retry_or_failed', 'discarded')} for s in stages},
                  p95=[duration_percentile([sum(durations[s][i][b] for s in stages) for b in range(len(DURATION_BOUNDS) + 1)], .95) for i in range(count)]),
        queues=dict(ready=ready, retry=retry, dead=dead),
        summary=dict(requests=all_requests, client_errors=all_client, server_errors=all_server,
                     error_rate=round(all_server / all_requests, 4) if all_requests else None,
                     p95=latency_percentile(total_latency, .95), p50=latency_percentile(total_latency, .5),
                     completed=completed, failed=failed, discarded=discarded,
                     failure_rate=round((failed + discarded) / (completed + failed + discarded), 4) if completed + failed + discarded else None),
        stages=stage_totals,
    )
