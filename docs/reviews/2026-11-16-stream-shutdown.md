# Live stream shutdown timeout

The reported Windows/Python 3.15 traceback ends in Uvicorn cancelling an ASGI
request after its 15-second graceful shutdown timeout. The user reported that
the app stopped without a deliberate Ctrl+C; the provided output did not include
an initiating signal, listener failure or supervisor decision.

## Reproduction and fix

A real HTTP test with an idle EventResponse behind FastAPI's HTTP middleware
reproduced the timeout. Uvicorn waits for active HTTP requests before sending
lifespan shutdown, while the browser stream never finishes by itself. Subscriber
cleanup in lifespan therefore occurs too late.

The server now closes only tracked live event requests before the HTTP-drain
wait. The admission layer recognizes only its own explicit cancellation reason,
completes the response and releases capacity. Ordinary API requests are not
targeted. Async event cleanup is shielded from Starlette task-group cancellation;
unrelated cancellations and real cleanup errors are still surfaced.

The Windows native event loop is retained. Other platforms use the same stream
shutdown hook and preserve Uvicorn's nonzero startup-failure exit status.

## Unexpected stop diagnosis

This fixes the reproduced cleanup timeout; it does not establish what initiated
the reported automatic shutdown. Runtime logs now identify received signals and
Windows listener failures, or state that no process signal was recorded. The
original origin supervisor should remain in start.bat with the existing tunnel
and hostname options so its recovery decisions are retained in its log.

## Verification

Focused tests cover real TCP streaming through the local-health wrapper and HTTP
middleware, asynchronous cleanup, ordinary requests remaining active, rejection
of new streams during shutdown, visible real errors/unrelated cancellations,
Windows loop wiring and failed-startup exit status. Existing database schemas
and running user services are not modified.

Final validation: 1,190 backend tests passed, 17 skipped, 102 subtests passed;
546 frontend tests passed; production build and release consistency passed.
The TCP reproduction ran in the available Linux environment. Windows native-loop
wiring is covered by platform-specific mocked tests; the original Windows/Python
3.15 deployment still needs confirmation with the updated shutdown diagnostics.
