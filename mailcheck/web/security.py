"""Shared HTTP limits and browser policies applied before routing/auth parsing."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

BODY_LIMIT = 4_000_000
AUTH_BODY_LIMIT = 16_384
BODY_IDLE_SECONDS = 15
BODY_TOTAL_SECONDS = 30


def policy_headers(*, secure_cookies=False, legacy_scripts=False):
    scripts = "'self' 'unsafe-inline'" if legacy_scripts else "'self'"
    headers = {
        b'x-content-type-options': b'nosniff',
        b'x-frame-options': b'DENY',
        b'referrer-policy': b'no-referrer',
        b'permissions-policy': b'camera=(), microphone=(), geolocation=()',
        b'content-security-policy': (
            "default-src 'self'; script-src " + scripts +
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self'; connect-src 'self'; frame-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        ).encode(),
    }
    if secure_cookies:
        headers[b'strict-transport-security'] = b'max-age=31536000'
    return headers


def install_http_boundary(app, **options):
    # Starlette's 500 handler runs outside user middleware; apply the same
    # policies explicitly so unexpected failures are private and non-cacheable.
    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        headers = {key.decode(): value.decode() for key, value in policy_headers(
            secure_cookies=options.get('secure_cookies', False),
            legacy_scripts=options.get('legacy_scripts', False)).items()}
        headers['Cache-Control'] = 'no-store'
        return JSONResponse({'error': 'Internal server error.'}, status_code=500, headers=headers)
    app.add_middleware(HTTPBoundary, **options)


class HTTPBoundary:
    def __init__(self, app, *, secure_cookies=False, legacy_scripts=False,
                 public_hosts=None, internal_hosts=None):
        self.app = app
        self.secure_cookies = secure_cookies
        self.legacy_scripts = legacy_scripts
        self.public_hosts = set(public_hosts or [])
        self.internal_hosts = set(internal_hosts or ['127.0.0.1', 'localhost', '::1', 'testserver'])

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def protected_send(message):
            if message['type'] == 'http.response.start':
                original_headers = message.get('headers', [])
                headers = policy_headers(secure_cookies=self.secure_cookies,
                                         legacy_scripts=self.legacy_scripts)
                if not any(key.lower() == b'cache-control' for key, _ in original_headers):
                    headers[b'cache-control'] = b'no-store'
                message = {**message, 'headers': [(key, value) for key, value in original_headers
                    if key.lower() not in headers] + list(headers.items())}
            await send(message)

        async def deny(status, error):
            await JSONResponse({'error': error}, status_code=status)(scope, receive, protected_send)

        hosts = [value.decode('latin-1') for key, value in scope['headers'] if key.lower() == b'host']
        try:
            if len(hosts) != 1 or any(c in hosts[0] for c in '/\\@?# \t\r\n'):
                raise ValueError
            parsed = urlsplit('//' + hosts[0])
            host = parsed.hostname
            _ = parsed.port  # Validate malformed/oversized port strings too.
            if not host:
                raise ValueError
        except ValueError:
            return await deny(400, 'Invalid Host header.')
        if scope['path'].rstrip('/') in ('/openapi.json', '/docs', '/redoc'):
            return await deny(404, 'Not found.')
        internal = scope['path'].startswith('/_internal/')
        if internal and host.lower() not in self.internal_hosts:
            return await deny(403, 'Internal access denied.')
        if self.public_hosts and not internal and host.lower() not in self.public_hosts:
            return await deny(403, 'Use the configured public domain.')

        if self.public_hosts and not internal and scope.get('scheme') != 'https':
            return await deny(400, 'HTTPS is required. Check the trusted tunnel forwarding configuration.')

        lengths = [value for key, value in scope['headers'] if key.lower() == b'content-length']
        limit = AUTH_BODY_LIMIT if scope['path'].startswith('/api/auth/') else BODY_LIMIT
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                return await deny(400, 'Invalid Content-Length header.')
            # Avoid parsing an arbitrarily long attacker-supplied integer.
            if len(lengths[0]) > 10 or int(lengths[0]) > limit:
                return await deny(413, 'Request is too large.')
        # Bound streamed/chunked data too, before FastAPI JSON parsing allocates
        # an unbounded object. Existing routes can still read request.body().
        body = bytearray()
        deadline = time.monotonic() + BODY_TOTAL_SECONDS
        while True:
            try:
                message = await asyncio.wait_for(receive(), min(BODY_IDLE_SECONDS, max(0, deadline - time.monotonic())))
            except asyncio.TimeoutError:
                return await deny(408, 'Request body timed out.')
            if message['type'] == 'http.disconnect':
                return await deny(499, 'Client disconnected.')
            body.extend(message.get('body', b''))
            if len(body) > limit:
                return await deny(413, 'Request is too large.')
            if not message.get('more_body', False):
                break
        consumed = False
        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, protected_send)
