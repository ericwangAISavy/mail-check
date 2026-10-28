"""Bounded local workspace processes. Only the authenticated gateway faces LAN clients."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import os
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

import httpx

from .workspaces import backup_legacy


def gateway_address(host: str, port: int) -> str:
    """Reach the same listener for worker heartbeats, including specific binds."""
    target={'0.0.0.0':'127.0.0.1','::':'::1'}.get(host,host)
    authority=f'[{target}]' if ':' in target and not target.startswith('[') else target
    return f'http://{authority}:{port}'


class InstanceLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def __enter__(self):
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        try:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);self.file.write(b' ');self.file.flush();self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,BlockingIOError):
            self.file.close();raise RuntimeError('This OfferPath instance is already running.')
        return self
    def __exit__(self,*exc):
        if self.file:self.file.close()


@dataclass
class Worker:
    workspace_id: str
    port: int
    token: str
    process: subprocess.Popen
    log: object
    ready: bool = False
    started_at: float = field(default_factory=time.time)


class WorkerPool:
    def __init__(self,store,gateway_url,legacy_paths):
        self.store=store;self.gateway_url=gateway_url;self.legacy_paths=legacy_paths
        self.workers={};self.failures={};self.errors={};self.stopped=set();self.closing=False;self._lock=threading.RLock()

    def _backup(self):
        folder=self.store.root/'rollback-original'
        if folder.exists():
            try:
                manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
                expected=dict(zip(('config.toml','mailcheck.db','web-auth.json'),self.legacy_paths))
                if not isinstance(manifest,dict) or not set(manifest)<=set(expected):raise ValueError('Invalid backup marker.')
                for name,entry in manifest.items():
                    if entry['original']!=str(expected[name]) or not (folder/name).is_file():raise ValueError('Missing backup or changed source paths.')
                    digest=entry.get('sha256') or entry.get('backup_sha256')
                    if not isinstance(digest,str) or len(digest)!=64:raise ValueError('Invalid backup hash.')
            except (OSError,ValueError,KeyError,TypeError):
                raise RuntimeError('Original workspace backup is incomplete or invalid. Resolve it before starting workers.') from None
            return
        backup_legacy(folder,*self.legacy_paths)

    def ensure(self,workspace):
        wid=workspace['id']
        with self._lock:
            if self.closing or wid in self.stopped:raise RuntimeError('Workspace is suspended or shutting down.')
            current=self.workers.get(wid)
            if current and current.process.poll() is None:
                if current.ready:return current
                worker=current
            else:
                if current:
                    current.log.close();self.workers.pop(wid,None)
                worker=self._spawn(workspace)
        # Concurrent first requests share the same process and independently
        # wait for readiness. No gateway event-loop thread holds this lock.
        try:
            with httpx.Client(trust_env=False,timeout=1) as client:
                for _ in range(100):
                    if worker.process.poll() is not None:break
                    try:
                        if client.get(f'http://127.0.0.1:{worker.port}/_internal/ready',headers={'x-offerpath-worker':worker.token}).status_code==200:
                            worker.ready=True
                            self.errors.pop(wid,None)
                            return worker
                    except httpx.HTTPError:pass
                    time.sleep(.1)
            raise RuntimeError('Workspace worker could not start. Check workspace health logs.')
        except BaseException:
            # Do not terminate a replacement process started by another request.
            with self._lock:
                if self.workers.get(wid) is worker:self.stop(wid,suspended=False)
            raise

    def _spawn(self,workspace):
        wid=workspace['id']
        recent=[t for t in self.failures.get(wid,[]) if t>time.time()-300]
        if len(recent)>=3:raise RuntimeError('Workspace restart limit reached. Retry later or contact the owner.')
        if recent and time.time()-recent[-1] < min(60,10*2**(len(recent)-1)):
            raise RuntimeError('Workspace restart is waiting for a short recovery period.')
        if len(self.workers)>=self.store.max_workspaces:raise RuntimeError('Worker capacity reached.')
        if wid=='legacy':self._backup()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        token=secrets.token_urlsafe(48)
        env=os.environ.copy()
        for key in ('OFFERPATH_WORKSPACE_ROOT','OFFERPATH_WORKSPACE_ID','OFFERPATH_LEGACY_CONFIG_PATH','OFFERPATH_LEGACY_DB_PATH'):env.pop(key,None)
        if workspace['root']:
            env['OFFERPATH_WORKSPACE_ROOT']=workspace['root'];env['OFFERPATH_WORKSPACE_ID']=wid
        else:
            env['OFFERPATH_LEGACY_CONFIG_PATH']=str(self.legacy_paths[0])
            env['OFFERPATH_LEGACY_DB_PATH']=str(self.legacy_paths[1])
        env.update(OFFERPATH_WORKER_TOKEN=token,OFFERPATH_GATEWAY_URL=self.gateway_url,
                   OFFERPATH_WORKER_ID=wid,OFFERPATH_WORKER_LOCK=str(self.store.root/'runtime'/f'{wid}.lock'))
        logs=self.store.root/'logs';logs.mkdir(mode=0o700,exist_ok=True)
        log=(logs/f'{wid}.log').open('ab');os.chmod(log.name,0o600)
        process=subprocess.Popen([sys.executable,'-m','mailcheck.workspace_workers','--port',str(port)],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        worker=Worker(wid,port,token,process,log)
        self.workers[wid]=worker;self.failures[wid]=recent+[time.time()]
        return worker

    def authenticate_worker(self,token):
        with self._lock:
            for wid,worker in self.workers.items():
                if wid not in self.stopped and secrets.compare_digest(worker.token,token) and worker.process.poll() is None:return wid
        return None

    def stop(self,wid,*,suspended=True):
        with self._lock:
            if suspended:self.stopped.add(wid)
            worker=self.workers.pop(wid,None)
        if worker:
            worker.process.terminate()
            try:worker.process.wait(timeout=10)
            except subprocess.TimeoutExpired:worker.process.kill();worker.process.wait(timeout=5)
            worker.log.close()

    def enable(self,wid):
        with self._lock:self.stopped.discard(wid);self.failures.pop(wid,None)

    def status(self):
        with self._lock:
            return {**self.errors, **{wid:('running' if w.process.poll() is None and w.ready else 'starting or stopped') for wid,w in self.workers.items()}}

    def start_times(self):
        with self._lock:
            return {wid:worker.started_at for wid,worker in self.workers.items()}

    def close(self):
        with self._lock:
            self.closing=True
            ids=list(self.workers)
        for wid in ids:self.stop(wid)

    async def monitor(self):
        while True:
            await asyncio.sleep(5)
            for workspace in self.store.enabled_workspaces():
                try:await asyncio.to_thread(self.ensure,workspace)
                except (RuntimeError,OSError,ValueError) as exc:self.errors[workspace["id"]]=str(exc) if isinstance(exc,RuntimeError) else "Workspace startup failed."


def main():
    import argparse
    import urllib.request
    from .web.app import create_app
    from .web.server import run
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    token=os.environ['OFFERPATH_WORKER_TOKEN']
    def parent_watch():
        # Gateway tokens are regenerated on restart: orphaned workers stop.
        failures=0
        while True:
            time.sleep(5)
            try:
                req=urllib.request.Request(os.environ['OFFERPATH_GATEWAY_URL']+'/_internal/ping',headers={'x-offerpath-worker':token})
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as response:
                    failures=0 if response.status==200 else failures+1
            except Exception:failures+=1
            if failures>=3:os._exit(1)
    with InstanceLock(os.environ['OFFERPATH_WORKER_LOCK']):
        threading.Thread(target=parent_watch,daemon=True).start()
        run(create_app(worker_secret=token),host='127.0.0.1',port=args.port,log_level='warning')


if __name__=='__main__':main()
