import os
from unittest.mock import patch
import httpx
import pytest
from mailcheck.llm.workspace_queue import shared_model_slot


def test_private_prompt_is_not_sent_to_gateway_and_lease_is_released_on_failure():
    calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(200,json={'lease':'lease-token'} if request.url.path.endswith('/acquire') else {'ok':True})
    real_client=httpx.Client
    @shared_model_slot
    def complete(prompt):
        assert prompt=='private email content'
        raise RuntimeError('generation failed')
    with patch.dict(os.environ,{'OFFERPATH_GATEWAY_URL':'http://127.0.0.1:52400','OFFERPATH_WORKER_TOKEN':'private-token'}),patch('mailcheck.llm.workspace_queue.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(transport),**kw)):
        with pytest.raises(RuntimeError,match='generation failed'):complete('private email content')
    assert [r.url.path for r in calls]==['/_internal/model/acquire','/_internal/model/release']
    assert all(b'private email content' not in r.content for r in calls)
    assert b'lease-token' in calls[1].content


def test_standalone_mode_keeps_the_original_model_call_without_gateway():
    @shared_model_slot
    def complete():return 'original behavior'
    with patch.dict(os.environ,{'OFFERPATH_GATEWAY_URL':'','OFFERPATH_WORKER_TOKEN':''}),patch('mailcheck.llm.workspace_queue.httpx.Client') as client:
        assert complete()=='original behavior'
        client.assert_not_called()
