from datetime import datetime,timezone
from mailcheck.shared.live_inbox import SharedLiveInbox


def test_live_demand_is_visible_across_process_instances(tmp_path):
    first=SharedLiveInbox(tmp_path/'inbox.json')
    second=SharedLiveInbox(tmp_path/'inbox.json')
    first.heartbeat(7)
    assert second.active()=={7}
    assert second.reserve()
    assert not first.reserve()
    assert first.snapshot(True)['running']
    second.finish(True)
    assert first.snapshot(True)['last_check_ok']
    assert not first.due()
