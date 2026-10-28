"""Web server startup with a Windows-safe socket event loop."""
import asyncio
import sys

import uvicorn


def run(app, **options):
    if sys.platform != 'win32':
        return uvicorn.run(app, **options)
    # CPython's Proactor pipe transport can raise WinError 10054 from its
    # connection-lost callback when a browser resets an already closing socket.
    # Use the socket selector loop for this HTTP server, without changing the
    # process-wide policy or suppressing application/connection exceptions.
    server = uvicorn.Server(uvicorn.Config(app, **options, loop='asyncio'))
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(server.serve())
