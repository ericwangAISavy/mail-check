"""Bound model concurrency across isolated workspace processes."""
from functools import wraps
import os
import httpx


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
                try:client.post(gateway+'/_internal/model/release',headers={'x-offerpath-worker':token},json={'lease':lease},timeout=5)
                except httpx.HTTPError:pass  # Gateway lease timeout recovers a crashed worker.
    return run
