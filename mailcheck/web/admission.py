"""Bound active HTTP work separately from idle transport connections."""
from starlette.responses import JSONResponse


class RequestAdmission:
    # These short coordination calls must complete even while browser work or
    # model acquisitions occupy the ordinary request budget. Authentication
    # still runs inside the application; a header never grants access here.
    CONTROL_PATHS = {'/_internal/ping', '/_internal/ready', '/_internal/model/release'}

    def __init__(self, app, *, max_requests=64, max_control_requests=8):
        self.app = app
        self.max_requests = max_requests
        self.max_control_requests = max_control_requests
        self.active = 0
        self.control_active = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        peer = scope.get('client')
        control = (
            scope['path'] in self.CONTROL_PATHS
            and peer is not None and peer[0] in ('127.0.0.1', '::1')
            and any(key.lower() == b'x-offerpath-worker' and value
                    for key, value in scope.get('headers', []))
        )
        counter = 'control_active' if control else 'active'
        limit = self.max_control_requests if control else self.max_requests
        # No await between checking and reserving: requests share one server loop.
        if getattr(self, counter) >= limit:
            return await JSONResponse(
                {'error': 'Server is busy. Try again shortly.'}, status_code=503,
                headers={'Retry-After': '1', 'Cache-Control': 'no-store',
                         'Connection': 'close'},
            )(scope, receive, send)
        setattr(self, counter, getattr(self, counter) + 1)
        try:
            await self.app(scope, receive, send)
        finally:
            setattr(self, counter, getattr(self, counter) - 1)
