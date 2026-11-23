"""Correlate failed gateway/worker requests without logging queries or payloads."""
import logging
import os
import re
import time
import uuid

from ..shared.health_evidence import failure, safe_evidence


class RequestDiagnostics:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope,receive,send)
        headers = list(scope.get('headers',[]))
        candidates = [v for k,v in headers if k.lower()==b'x-request-id']
        try:
            request_id = str(uuid.UUID(candidates[0].decode('ascii'))) if len(candidates)==1 else str(uuid.uuid4())
        except (ValueError,UnicodeError):
            request_id = str(uuid.uuid4())
        headers = [(k,v) for k,v in headers if k.lower()!=b'x-request-id']+[(b'x-request-id',request_id.encode())]
        scope['headers'] = headers
        scope.setdefault('state',{})
        started, status, evidence = time.monotonic(), 500, {}
        async def report(message):
            nonlocal status
            if message['type']=='http.response.start':
                status = message['status']
                message = {**message,'headers':[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'x-request-id']+
                           [(b'x-request-id',request_id.encode())]}
            await send(message)
        try:
            await self.app(scope,receive,report)
        except Exception as exc:
            evidence = failure(exc)
            raise
        finally:
            evidence = evidence or safe_evidence(scope.get('state',{}).get('failure_evidence'))
            if status>=500 or evidence:
                route = '/'+ '/'.join(part if re.fullmatch('[a-z-]{1,40}',part) else ':id'
                                     for part in scope.get('path','').split('/')[1:3])
                identity = scope.get('state',{}).get('identity') or {}
                logging.getLogger(__name__).warning(
                    'Request failed request_id=%s worker=%s pid=%s workspace=%s method=%s route=%s http_status=%s duration_ms=%.1f evidence=%s',
                    request_id,os.environ.get('OFFERPATH_WORKER_ID','gateway'),os.getpid(),identity.get('workspace_id','unknown'),
                    scope.get('method'),route,status,(time.monotonic()-started)*1000,evidence)
