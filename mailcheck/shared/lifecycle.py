"""Parent authentication and graceful shutdown for shared child processes."""
from __future__ import annotations

import logging
import os
import threading
import urllib.error
import urllib.request


def _probe_parent():
    request = urllib.request.Request(
        os.environ['OFFERPATH_GATEWAY_URL'].rstrip('/') + '/_internal/ping',
        headers={'x-offerpath-worker': os.environ['OFFERPATH_WORKER_TOKEN']})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def supervise(server, stop_callback=None, *, probe=None, interval=5):
    """Watch parent authentication; return a callable that stops the watcher.

    The callback must stop accepting new work before draining consumers. Server
    shutdown is requested in a finally block so callback failures cannot leave
    an unauthenticated API listening indefinitely.
    """
    stopped = threading.Event()
    from .service_health import report_service
    stop_reporting = report_service(server)
    probe = probe or _probe_parent

    def watch():
        failures = 0
        while not stopped.wait(interval):
            try:
                status = probe()
                if status in (200, 503):
                    if failures:
                        logging.getLogger(__name__).info('Gateway contact restored; shared process continued running.')
                    failures = 0
                    continue
                revoked = status in (401, 403)
                failures += 1
            except Exception:
                revoked = False
                failures += 1
            if not revoked:
                if failures == 3:
                    logging.getLogger(__name__).warning('Gateway is temporarily unreachable; shared process remains running with local workspace access checks.')
                continue
            logging.getLogger(__name__).warning('Gateway revoked worker authentication; draining this shared process.')
            try:
                if stop_callback is not None:
                    stop_callback()
            except Exception:
                logging.getLogger(__name__).exception('Shared process stop callback failed.')
            finally:
                server.should_exit = True
            return

    thread = threading.Thread(target=watch, name='offerpath-parent-watch', daemon=True)
    thread.start()

    def cleanup():
        stopped.set()
        if threading.current_thread() is not thread:
            thread.join(timeout=4)
        stop_reporting()

    return cleanup
