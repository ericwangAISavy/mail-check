"""Bound active HTTP work separately from idle transport connections."""
import asyncio
from starlette.responses import JSONResponse


class RequestAdmission:
    # These short coordination calls must complete even while browser work or
    # model acquisitions occupy the ordinary request budget. Authentication
    # still runs inside the application; a header never grants access here.
    CONTROL_PATHS = {'/_internal/ping', '/_internal/ready', '/_internal/model/release'}

    def __init__(self, app, *, max_requests=64, max_control_requests=8, max_streams=128, max_callbacks=8, stream_send_timeout=10):
        self.app = app
        self.max_requests = max_requests
        self.max_control_requests = max_control_requests
        self.active = 0
        self.control_active = 0
        self.max_streams = max_streams
        self.max_callbacks = max_callbacks
        self.stream_active = 0
        self.callback_active = 0
        self.stream_send_timeout = stream_send_timeout
        self.closing = False
        self._streams = set()
        self._shutdown_streams = set()

    def begin_shutdown(self):
        """End indefinite browser streams before Uvicorn waits for HTTP drain."""
        self.closing = True
        for task in tuple(self._streams):
            if not task.done() and not task.cancelling():
                self._shutdown_streams.add(task)
                task.cancel('OfferPath closing live event stream')

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
        if scope['path'] == '/api/realtime/events':
            counter, limit = 'stream_active', self.max_streams
        elif scope['path'] == '/hooks/microsoft':
            counter, limit = 'callback_active', self.max_callbacks
        # No await between checking and reserving: requests share one server loop.
        if getattr(self, counter) >= limit or (counter == 'stream_active' and self.closing):
            return await JSONResponse(
                {'error': 'Server is busy. Try again shortly.'}, status_code=503,
                headers={'Retry-After': '1', 'Cache-Control': 'no-store',
                         'Connection': 'close'},
            )(scope, receive, send)
        setattr(self, counter, getattr(self, counter) + 1)
        task = asyncio.current_task()
        if counter == 'stream_active':
            self._streams.add(task)
        timed_out = False
        response_started = False
        response_complete = False
        async def bounded_send(message):
            nonlocal timed_out, response_started, response_complete
            try:
                await asyncio.wait_for(send(message), self.stream_send_timeout)
                if message['type'] == 'http.response.start':
                    response_started = True
                elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                    response_complete = True
            except TimeoutError:
                timed_out = True
                raise
        try:
            await self.app(scope, receive, bounded_send if counter == 'stream_active' else send)
        except asyncio.CancelledError as exc:
            if task not in self._shutdown_streams or exc.args != ('OfferPath closing live event stream',):
                raise
            # Only our explicit stream shutdown is expected. Do not hide
            # unrelated cancellations/errors or interrupt ordinary API work.
            try:
                if not response_started:
                    await JSONResponse({'error':'Server is shutting down.'},503,
                        headers={'Retry-After':'1','Connection':'close'})(scope, receive, bounded_send)
                elif not response_complete:
                    await bounded_send({'type':'http.response.body','body':b'','more_body':False})
            except (OSError, TimeoutError):
                pass  # A disconnected/slow event subscriber cannot hold drain.
        except TimeoutError:
            if not timed_out:
                raise
        finally:
            self._streams.discard(task)
            self._shutdown_streams.discard(task)
            setattr(self, counter, getattr(self, counter) - 1)
