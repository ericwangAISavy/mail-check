"""Bound model concurrency across isolated workspace processes."""
from functools import wraps
import os
import logging
import time
import httpx


def _release_lease(client, gateway, token, lease):
    # Release is idempotent, so retry the same lease after a lost response or
    # transient admission failure. Never log credentials or replace a model error.
    for attempt in range(3):
        try:
            result = client.post(gateway+'/_internal/model/release',
                                 headers={'x-offerpath-worker': token},
                                 json={'lease': lease}, timeout=5)
            if result.is_success:
                return
            retry = result.status_code in (429, 500, 502, 503, 504)
        except httpx.HTTPError:
            retry = True
        if not retry or attempt == 2:
            break
        time.sleep(0.2 * (attempt + 1))
    logging.getLogger(__name__).warning(
        'Could not release shared model lease; gateway expiry will recover capacity.')


def shared_model_slot(operation):
    @wraps(operation)
    def run(*args,**kwargs):
        gateway=os.environ.get('OFFERPATH_GATEWAY_URL')
        token=os.environ.get('OFFERPATH_WORKER_TOKEN')
        if not gateway or not token:return operation(*args,**kwargs)
        from .client import OllamaBusy
        with httpx.Client(trust_env=False,timeout=610) as client:
            try:
                result=client.post(gateway+'/_internal/model/acquire',headers={'x-offerpath-worker':token})
                result.raise_for_status();lease=result.json()['lease']
            except (httpx.HTTPError,ValueError,KeyError) as exc:
                raise OllamaBusy('The shared model queue is unavailable. Try again shortly.',category='connect') from exc
            try:return operation(*args,**kwargs)
            finally:
                _release_lease(client,gateway,token,lease)
    return run
