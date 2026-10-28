import json
from unittest.mock import patch, MagicMock
from tests import test_frontend_api as fixtures
from mailcheck import assistant, config, db
from mailcheck.web import app as web_app

import unittest
class AssistantTests(unittest.TestCase):
    setUp=fixtures.FrontendApiTests.setUp
    add_message=fixtures.FrontendApiTests.add_message

def model():
    client=MagicMock();client.__enter__.return_value=client;client.model='existing-model'
    client.complete.return_value=json.dumps({'body':'Thank you for the update.'})
    return client

def test_generation_is_explicit_scoped_and_never_sends():
    case=AssistantTests();case.setUp()
    try:
        pk=case.add_message('assistant')
        cfg=config.Config();cfg.llm.base_url='http://model.test'
        client=model()
        with patch.object(assistant.LLMClient,'from_config',return_value=client),patch('mailcheck.replies.send') as send:
            result=assistant.generate(case.conn,pk,assistant.GenerateBody(case='thank_you'),cfg)
        assert result['body']=='Thank you for the update.'
        assert not send.called
        assert db.get_message(case.conn,pk)['handled_at'] is None
        assert case.conn.execute('SELECT original_message_id FROM agent_drafts').fetchone()[0]=='<assistant@example.test>'
        payload=json.loads(client.complete.call_args.args[1])
        assert payload['selected_email']['subject'].endswith('assistant')
    finally: case.doCleanups()

def test_availability_cannot_be_invented_and_failures_do_not_generate():
    case=AssistantTests();case.setUp()
    try:
        pk=case.add_message('availability');cfg=config.Config();cfg.llm.base_url='http://model.test';client=model()
        client.complete.return_value=json.dumps({'body':'Tomorrow at 2 AM guaranteed.'})
        free={'ranges':[{'label':'Fri, Oct 23: 10:00 AM–4:00 PM CDT'}],'timezone':'America/Chicago','checked_at':'now','calendar_labels':['work']}
        with patch.object(assistant.LLMClient,'from_config',return_value=client),patch.object(assistant.availability,'refresh',return_value=free):
            result=assistant.generate(case.conn,pk,assistant.GenerateBody(case='availability',duration_minutes=60),cfg)
        assert '2 AM' not in result['body'];assert free['ranges'][0]['label'] in result['body']
        client.reset_mock()
        with patch.object(assistant.LLMClient,'from_config',return_value=client),patch.object(assistant.availability,'refresh',side_effect=ValueError('Calendar offline')):
            import pytest
            with pytest.raises(ValueError,match='Could not verify'): assistant.generate(case.conn,pk,assistant.GenerateBody(case='availability'),cfg)
        client.complete.assert_not_called()
    finally: case.doCleanups()

def test_context_preferences_and_busy_api():
    case=AssistantTests();case.setUp()
    try:
        pk=case.add_message('context')
        response=case.client.get(f'/api/agent/messages/{pk}')
        assert response.status_code==200
        prefs=response.json()['preferences'];assert prefs['friday_end_hour']==16;assert prefs['lookahead_business_days']==5
        assert case.client.post(f'/api/agent/preferences/{case.account_id}',json={**prefs,'sender_name':'Eric'}).status_code==200
        assert case.client.get(f'/api/agent/preferences/{case.account_id}').json()['sender_name']=='Eric'
        with patch.object(web_app,'_job_lock') as lock:
            lock.acquire.return_value=False
            assert case.client.post(f'/api/agent/messages/{pk}/generate',json={'case':'reschedule'}).status_code==409
        assert case.client.get('/api/agent/messages/999999').status_code==404
    finally: case.doCleanups()

def test_saved_draft_recovery_identity_and_deleted_account_preferences():
    case=AssistantTests();case.setUp()
    try:
        pk=case.add_message('saved');cfg=config.Config();cfg.llm.base_url='http://model.test'
        with patch.object(assistant.LLMClient,'from_config',return_value=model()):
            assistant.generate(case.conn,pk,assistant.GenerateBody(case='reschedule'),cfg)
        assert assistant.context(case.conn,pk,cfg)['saved_draft']['body']
        case.conn.execute('UPDATE messages SET message_id=? WHERE id=?',('<replacement>',pk))
        assert assistant.context(case.conn,pk,cfg)['saved_draft'] is None
        assistant.save_preferences(case.conn,case.account_id,assistant.Preferences(sender_name='Old identity'))
        db.remove_account(case.conn,'personal')
        assert case.conn.execute('SELECT * FROM agent_preferences').fetchone() is None
    finally:case.doCleanups()
