"""HTTP startup using Windows' native IOCP event loop."""
import asyncio
import logging
import inspect
import sys

import uvicorn

from .admission import RequestAdmission

log = logging.getLogger('uvicorn.error')


class LocalOriginHealth:
    """Direct loopback probe; forwarded/public traffic retains normal auth checks."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        peer = scope.get('client')
        forwarded = any(key.lower() in (b'x-forwarded-for', b'forwarded') for key, _ in scope.get('headers', []))
        if (scope['type'] == 'http' and scope.get('path') == '/_internal/origin-health'
                and scope.get('method') in ('GET', 'HEAD') and peer
                and peer[0] in ('127.0.0.1', '::1') and not forwarded):
            from starlette.responses import Response
            return await Response(status_code=204, headers={'X-OfferPath-Health':'1', 'Cache-Control':'no-store'})(scope, receive, send)
        return await self.app(scope, receive, send)


def windows_exception_handler(server, failures):
    def handle(loop, context):
        error = context.get('exception')
        if isinstance(error, OSError) and context.get('message') == 'Accept failed on a socket' and context.get('socket') is not None:
            # Proactor closes the failed listening socket. Uvicorn otherwise
            # continues serving its main loop with no working HTTP listener.
            # Let lifespan cleanup finish and make the failure visible to the
            # launcher/worker supervisor instead of leaving a zombie server.
            loop.default_exception_handler(context)
            if not failures:
                failures.append(error)
                log.error('Windows HTTP listener failed; shutting down cleanly so the foreground launcher can recover.')
            server.should_exit = True
            return
        callback = getattr(context.get('handle'), '_callback', None)
        transport = getattr(callback, '__self__', None)
        closing_reset = (
            isinstance(error, ConnectionResetError)
            and getattr(error, 'winerror', None) == 10054
            and getattr(callback, '__name__', '') == '_call_connection_lost'
            and any(cls.__name__ == '_ProactorBasePipeTransport' for cls in type(transport).__mro__)
            and transport.is_closing()
        )
        if closing_reset:
            # A peer reset during an already-closing transport is not a
            # listening-socket failure. Do not mask other transport/app errors.
            try:
                # CPython 3.12 can raise from socket.shutdown() before close
                # and server detach run. Finish that cleanup without calling
                # protocol.connection_lost a second time.
                sock = getattr(transport, '_sock', None)
                if sock is not None:
                    sock.close()
                    transport._sock = None
                owner = getattr(transport, '_server', None)
                if owner is not None:
                    # Server._detach has changed across supported Python releases.
                    if inspect.signature(owner._detach).parameters:
                        owner._detach(transport)
                    else:
                        owner._detach()
                    transport._server = None
                transport._called_connection_lost = True
            except Exception as cleanup_error:
                loop.default_exception_handler(context)
                loop.default_exception_handler({'message':'Windows connection cleanup failed','exception':cleanup_error})
                return
            log.debug('Windows peer reset while closing an HTTP connection', exc_info=error)
            return
        loop.default_exception_handler(context)
    return handle


def run(app, *, health_check=False, **options):
    # Ignore environment-wide wildcard proxy trust. Only a same-machine proxy
    # may supply visitor addresses and the HTTPS scheme.
    options.setdefault('proxy_headers', True)
    options.setdefault('forwarded_allow_ips', '127.0.0.1,::1')
    options.setdefault('server_header', False)
    # Uvicorn counts idle keep-alive sockets, so allow finite transport
    # headroom while the ASGI wrapper independently bounds active work.
    options.setdefault('limit_concurrency', 256)
    app = RequestAdmission(app)
    if health_check:
        app = LocalOriginHealth(app)
    options.setdefault('timeout_keep_alive', 5)
    options.setdefault('timeout_graceful_shutdown', 15)
    if sys.platform != 'win32':
        return uvicorn.run(app, **options)
    # The previous forced Selector loop can repeatedly call accept() on a
    # socket rejected by Winsock (10022), consuming CPU without serving HTTP.
    # Use native Windows IOCP, without changing the process-wide loop policy.
    server = uvicorn.Server(uvicorn.Config(app, **options, loop='asyncio'))
    failures = []
    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        runner.get_loop().set_exception_handler(windows_exception_handler(server, failures))
        result = runner.run(server.serve())
        if failures:
            raise failures[0]
        return result
