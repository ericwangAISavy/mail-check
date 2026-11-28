"""Cross-process bidder demand without adding database tables."""
from datetime import datetime, timezone
import json
import time

from ..live_inbox import ACTIVE_SECONDS, INTERVAL_SECONDS
from .state import OperationLock, atomic_json


class SharedLiveInbox:
    def __init__(self,path):
        self.path=path
        self.lock=OperationLock(path.with_suffix('.lock'))

    def _read(self):
        try:
            state=json.loads(self.path.read_text())
        except FileNotFoundError:
            state={}
        now=time.time()
        state['seen']={who:at for who,at in state.get('seen',{}).items() if now-at<=ACTIVE_SECONDS}
        if state.get('running_until',0)<=now:
            state['running_until']=0
        return state

    def heartbeat(self,bidder_id):
        with self.lock:
            state=self._read()
            state['seen'][str(bidder_id)]=time.time()
            atomic_json(self.path,state)

    def active(self):
        return {int(who) for who in self._read()['seen']}

    def due(self):
        state=self._read()
        return bool(state['seen']) and not state['running_until'] and time.time()>=state.get('next',0)

    def reserve(self):
        with self.lock:
            state=self._read()
            if not state['seen'] or state['running_until'] or time.time()<state.get('next',0):
                return False
            now=time.time()
            state.update(running_until=now+900,attempt=datetime.now(timezone.utc).isoformat(),next=now+INTERVAL_SECONDS)
            atomic_json(self.path,state)
            return True

    def finish(self,success=False):
        with self.lock:
            state=self._read()
            state.update(running_until=0,last_ok=bool(success),next=max(state.get('next',0),time.time()+(INTERVAL_SECONDS if success else 60)))
            if success:
                state['last']=datetime.now(timezone.utc).isoformat()
            atomic_json(self.path,state)

    def snapshot(self,enabled,disabled_reason=None):
        state=self._read()
        return dict(enabled=bool(enabled),interval_seconds=INTERVAL_SECONDS,running=bool(state['running_until']),
            last_checked_at=state.get('last'),last_attempt_at=state.get('attempt'),last_check_ok=state.get('last_ok'),
            disabled_reason=disabled_reason if not enabled else None,
            next_at=datetime.fromtimestamp(max(time.time(),state.get('next',0)),timezone.utc).isoformat() if enabled else None)
