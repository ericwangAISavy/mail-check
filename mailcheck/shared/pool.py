"""A fixed number of API processes shared by all authenticated workspaces."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import socket
import subprocess
import sys
import time

from ..workspace_workers import Worker, WorkerPool


class SharedPool(WorkerPool):
    def __init__(self, store, gateway_url, legacy_paths, size=2, job_size=2, amqp_url=None):
        if not isinstance(size, int) or not 1 <= size <= 64:
            raise ValueError('Choose 1–64 shared API processes.')
        if not isinstance(job_size, int) or not 1 <= job_size <= 64:
            raise ValueError('Choose 1–64 collection processes.')
        super().__init__(store, gateway_url, legacy_paths)
        self.size = size
        self.amqp_url = amqp_url or os.environ.get('AMQP_URL')
        self.assignments = {}
        self.job_slots = ([f'shared-job-collection-{i}' for i in range(job_size)] + ['shared-job-model-0']) if self.amqp_url else []
        self._slots = {f'shared-api-{i}' for i in range(size)} | set(self.job_slots)

    def slot(self, wid):
        index = int.from_bytes(hashlib.sha256(wid.encode()).digest(), 'big') % self.size
        return f'shared-api-{index}'

    def ensure(self, workspace):
        wid = workspace['id']
        with self._lock:
            if self.closing or wid in self.stopped:
                raise RuntimeError('Workspace is suspended or shutting down.')
            slot = self.slot(wid)
            self.assignments[wid] = slot
        worker = super().ensure({'id': slot})
        with self._lock:
            if self.closing or wid in self.stopped:
                raise RuntimeError('Workspace is suspended or shutting down.')
        return worker

    def _spawn(self, workspace):
        slot = workspace['id']
        recent = [at for at in self.failures.get(slot, []) if at > time.time()-300]
        if len(recent) >= 3:
            raise RuntimeError('Shared API restart limit reached. Retry later.')
        if recent and time.time()-recent[-1] < min(60, 10*2**(len(recent)-1)):
            raise RuntimeError('Shared API restart is waiting for recovery.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = secrets.token_urlsafe(48)
        lane = ('collection' if slot.startswith('shared-job-collection-') else 'model') if slot in self.job_slots else None
        env = os.environ.copy()
        for key in ('OFFERPATH_WORKSPACE_ROOT', 'OFFERPATH_WORKSPACE_ID', 'OFFERPATH_SHARED_CONFIG_PATH', 'OFFERPATH_WORKER_LOCK'):
            env.pop(key, None)
        env.update(OFFERPATH_CONTROL_ROOT=str(self.store.root),
                   OFFERPATH_LEGACY_CONFIG_PATH=str(self.legacy_paths[0]),
                   OFFERPATH_LEGACY_DB_PATH=str(self.legacy_paths[1]),
                   OFFERPATH_WORKER_TOKEN=token, OFFERPATH_WORKER_ID=slot,
                   OFFERPATH_GATEWAY_URL=self.gateway_url,
                   OFFERPATH_REALTIME_REGISTRY=str(self.store.root/'realtime.db'))
        env['OFFERPATH_WORKER_MODE'] = 'shared'
        if self.amqp_url:
            env['AMQP_URL'] = self.amqp_url
        if lane:
            env['OFFERPATH_JOB_LANE'] = lane
            if slot == 'shared-job-collection-0':
                env['OFFERPATH_COORDINATOR'] = '1'
            else:
                env.pop('OFFERPATH_COORDINATOR', None)
        else:
            env.pop('OFFERPATH_JOB_LANE', None)
            env.pop('OFFERPATH_COORDINATOR', None)
        from ..maintenance import lock_path
        env['OFFERPATH_MAINTENANCE_LOCK'] = str(lock_path(self.legacy_paths[0]))
        logs = self.store.root/'logs'
        logs.mkdir(mode=0o700, exist_ok=True)
        log = (logs/f'{slot}.log').open('ab')
        os.chmod(log.name, 0o600)
        try:
            module = 'mailcheck.shared.runtime' if lane else 'mailcheck.shared.api'
            command = [sys.executable, '-m', module, '--port', str(port)]
            if lane:
                command.extend(['--lane', lane])
            process = subprocess.Popen(command,
                                       env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        except BaseException:
            log.close()
            raise
        worker = Worker(slot, port, token, process, log)
        self.workers[slot] = worker
        self.failures[slot] = recent + [time.time()]
        return worker

    def stop(self, wid, *, suspended=True, expected=None, only_unready=False):
        # Only pool-owned slot identities may retire a process. Admin suspension
        # affects routing, never another workspace's in-flight requests.
        if wid in self._slots:
            if not only_unready:
                # SIGTERM requests uvicorn shutdown; the job lifespan drains its
                # current operation. Never escalate an active job to SIGKILL.
                with self._lock:
                    worker=self.workers.get(wid)
                    if expected is not None and worker is not expected:return False
                    if only_unready and worker and worker.ready:return False
                    worker=self.workers.get(wid)
                    if worker:self._retiring.add(wid)
                if worker:
                    try:
                        if worker.process.poll() is None:
                            worker.process.terminate()
                        worker.process.wait()
                    finally:
                        worker.log.close()
                        with self._lock:
                            if self.workers.get(wid) is worker:
                                self.workers.pop(wid,None)
                            self._retiring.discard(wid)
                    return True
                return False
            return super().stop(wid, suspended=False, expected=expected, only_unready=only_unready)
        with self._lock:
            if suspended:
                self.stopped.add(wid)
            self.assignments.pop(wid, None)
        return True

    def check_health(self, wid):
        return super().check_health(self.slot(wid))

    def status(self):
        statuses = super().status()
        with self._lock:
            return {wid: statuses.get(slot, 'starting or stopped') for wid, slot in self.assignments.items()}

    def start_times(self):
        with self._lock:
            return {wid: self.workers[slot].started_at for wid, slot in self.assignments.items() if slot in self.workers}


    async def _monitor_jobs(self):
        while True:
            for slot in self.job_slots:
                try:
                    await asyncio.to_thread(super().check_health, slot)
                    await asyncio.to_thread(super().ensure, {'id': slot})
                except (RuntimeError, OSError, ValueError) as exc:
                    self.errors[slot] = str(exc)
                    logging.getLogger(__name__).warning('Shared job process %s unavailable: %s', slot, exc)
            await asyncio.sleep(5)

    async def monitor(self):
        jobs = asyncio.create_task(self._monitor_jobs())
        try:
            await super().monitor()
        finally:
            jobs.cancel()
            try:
                await jobs
            except asyncio.CancelledError:
                pass
