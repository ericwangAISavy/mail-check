"""Authenticated ASGI workspace dispatch for each fixed shared API process."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import secrets
import sqlite3

from starlette.responses import JSONResponse

from ..workspaces import WorkspaceContext, bind_workspace


class WorkspaceDispatcher:
    def __init__(self, app, reader, worker_secret, legacy_paths):
        if not worker_secret:
            raise ValueError('Shared API requires a worker secret.')
        self.app = app
        self.reader = reader
        self.worker_secret = worker_secret
        self.legacy_paths = legacy_paths

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            return
        headers = scope.get('headers', [])
        tokens = [v for k, v in headers if k.lower() == b'x-offerpath-worker']
        valid = len(tokens) == 1 and secrets.compare_digest(tokens[0], self.worker_secret.encode())
        if not valid:
            return await JSONResponse({'detail': 'Forbidden'}, status_code=403)(scope, receive, send)
        if scope.get('path') == '/_internal/ready':
            return await JSONResponse({'ready': True})(scope, receive, send)
        targets = [v for k, v in headers if k.lower() == b'x-offerpath-workspace']
        try:
            if len(targets) != 1:
                raise ValueError('Workspace required.')
            wid = targets[0].decode('ascii')
            record = await asyncio.to_thread(self.reader.workspace, wid)
            context = WorkspaceContext.from_record(record, self.legacy_paths, self.reader.root)
        except sqlite3.Error:
            return await JSONResponse({'detail': 'Workspace registry unavailable'}, status_code=503)(scope, receive, send)
        except (UnicodeError, ValueError, OSError):
            return await JSONResponse({'detail': 'Workspace unavailable'}, status_code=403)(scope, receive, send)
        # Keep context through response streaming and ASGI background tasks.
        # Starlette copies this context into its synchronous endpoint threads.
        with bind_workspace(context):
            return await self.app(scope, receive, send)


def create_dispatcher(reader, worker_secret, legacy_paths, app=None):
    if app is None:
        from ..web.app import create_app
        # App construction registers routes once; request data always comes
        # from the dispatcher binding, including the original workspace.
        context = WorkspaceContext.from_record({'id': 'legacy', 'root': None}, legacy_paths, reader.root)
        with bind_workspace(context):
            app = create_app(worker_secret=worker_secret, shared=True)
    return WorkspaceDispatcher(app, reader, worker_secret, legacy_paths)


def main():
    import argparse
    import uvicorn
    from .control import ControlReader
    from .lifecycle import supervise
    from ..workspace_workers import InstanceLock
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    root = Path(os.environ['OFFERPATH_CONTROL_ROOT'])
    config_path = Path(os.environ['OFFERPATH_LEGACY_CONFIG_PATH'])
    legacy = (config_path, Path(os.environ['OFFERPATH_LEGACY_DB_PATH']), config_path.parent/'web-auth.json')
    slot = os.environ['OFFERPATH_WORKER_ID']
    if not slot.startswith('shared-api-') or not slot.removeprefix('shared-api-').isdigit():
        raise ValueError('Invalid shared API slot identity.')
    with InstanceLock(root/'shared-runtime'/'processes'/f'{slot}.lock'):
        reader = ControlReader(root, legacy)
        app = create_dispatcher(reader, os.environ['OFFERPATH_WORKER_TOKEN'], legacy)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False))
        stop_watch = supervise(server)
        try:
            server.run()
        finally:
            stop_watch()


if __name__ == '__main__':
    main()
