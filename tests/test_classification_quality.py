import json
from datetime import datetime, timezone

import pytest

from mailcheck import normalize, prefilter
from mailcheck.models import RawMessage
from mailcheck.taxonomy import coerce_category
from mailcheck.llm.classify import classify


def message(subject='', text='', sender='noreply@indeed.com', **kwargs):
    raw = RawMessage('quality', '1', 'INBOX', sender, '', subject, datetime(2026, 11, 4), text, **kwargs)
    return normalize.normalize(raw, account_id=0, account_label='synthetic')


@pytest.mark.parametrize('subject,text', [
    ('Interview scheduling', 'Please choose a time for your interview.'),
    ('Application received', 'We received your application.'),
    ('Your job alert and application update', 'We received your application.'),
    ('Hello', 'A personal message without digest evidence.'),
])
def test_shared_senders_require_digest_evidence(subject, text):
    assert prefilter.apply(message(subject, text)) is None


def test_clear_digest_still_skips_model():
    assert prefilter.apply(message('Your daily job digest', 'New jobs matching your search')).category == 'job_alert'


@pytest.mark.parametrize('raw', ['not_interview_invite', 'application', 'interview', 'other than rejection'])
def test_category_names_cannot_be_guessed(raw):
    assert coerce_category(raw) == 'unclassified'


def test_long_message_keeps_tail_within_budget():
    msg = message('Update', 'Welcome ' * 230 + '\nPlease schedule your interview with Acme.')
    assert 'schedule your interview' in msg.body
    assert len(msg.body) <= 1200


def test_calendar_evidence_has_bounded_context():
    msg = message('Invitation', 'Please see the attached invitation.', calendar_data=[
        'BEGIN:VEVENT\nSUMMARY:Acme interview\nDTSTART:20261105T120000Z\nEND:VEVENT'])
    assert 'Acme interview' in msg.body
    assert len(msg.body) <= 1200


def test_sparse_reply_retains_labelled_quote():
    msg = message('Re: next step', 'Tuesday works.\nOn Monday Sam wrote:\n> Pick an interview time for Acme.')
    assert 'Quoted context' in msg.body and 'interview time' in msg.body


def test_current_rejection_does_not_recover_old_invite():
    msg = message('Decision', 'We are proceeding with other candidates.\nOn Monday Sam wrote:\n> Please schedule your interview.')
    assert 'schedule your interview' not in msg.body


class Replies:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return json.dumps({'results': [next(self.replies)]})


def test_incomplete_model_result_is_retried_not_accepted():
    client = Replies([{'id': '0', 'category': 'application_ack'},
                      {'id': '1', 'category': 'application_ack', 'confidence': .95,
                       'action_required': False, 'summary': 'Application received.'}])
    results, _ = classify(client, [message('Receipt', 'We received your application.')])
    assert client.calls == 2
    assert results[0].category == 'application_ack'


def test_repeated_incomplete_result_surfaces_for_review():
    client = Replies([{'id': str(i), 'category': 'job_alert'} for i in (0, 1, 1)])
    results, _ = classify(client, [message('Interview', 'Please schedule your interview.')])
    assert results[0].category == 'unclassified'
    assert results[0].action_required is True
    assert client.calls == 2


def test_uncertain_noise_about_interview_requires_review():
    client = Replies([{'id': str(i), 'category': 'other', 'confidence': .3,
                       'needs_review': True, 'action_required': False, 'summary': 'Unclear interview email.'}
                      for i in (0, 1, 1)])
    results, _ = classify(client, [message('Interview rescheduled', 'Your interview has moved.')])
    assert results[0].category == 'unclassified'


def test_normal_checks_preserve_labels_from_previous_prompt(tmp_path):
    from mailcheck import db
    from mailcheck.models import Classification
    with db.session(tmp_path / 'cache.db') as conn:
        msg = message('Receipt', 'Application received.')
        msg.account_id = db.add_account(conn, label='synthetic', email='test@example.test')
        pk = db.upsert_message(conn, msg)
        db.save_classification(conn, pk, Classification(category='application_ack'), 'same-model', '1')
        cached = db.get_cached(conn, pk, None)
        assert cached is not None and cached.category == 'application_ack'


@pytest.mark.parametrize('confidence', ['high', float('nan'), True, -1])
def test_invalid_confidence_is_not_accepted(confidence):
    from mailcheck.llm.schema import ItemResult
    item = ItemResult.model_validate({'id': '1', 'category': 'application_ack',
        'confidence': confidence, 'action_required': False, 'summary': 'Receipt.'})
    assert item.response_complete is False


def test_middle_interview_evidence_survives_long_boilerplate():
    msg = message('Update', 'Welcome to our portal. ' * 70 + '\nPlease schedule your interview at Acme.\n' + 'Portal information. ' * 70)
    assert 'schedule your interview' in msg.body
    assert len(msg.body) <= 1200


def test_ordinary_pipeline_uses_latest_label_across_prompt_versions(tmp_path, monkeypatch):
    # Check the ordinary run, not just the cache helper, without model access.
    from mailcheck import db, pipeline
    from mailcheck.models import Classification
    from mailcheck.config import Config
    msg = message('Receipt', 'Application received.')
    # This tests cache reuse, not retention; keep the fixture inside the window.
    msg.date_utc = datetime.now(timezone.utc)
    with db.session(tmp_path / 'pipeline.db') as conn:
        msg.account_id = db.add_account(conn, label='synthetic', email='test@example.test')
        pk = db.upsert_message(conn, msg)
        db.save_classification(conn, pk, Classification(category='application_ack'), 'old-model', '1')
        monkeypatch.setattr(pipeline, 'fetch_account', lambda *a, **k: [msg])
        monkeypatch.setattr(pipeline.interviews, 'process_run', lambda *a, **k: [])
        monkeypatch.setattr(pipeline.prefilter, 'apply', lambda *a, **k: pytest.fail('stored label bypassed'))
        result = pipeline.check_once(conn, Config())
        assert result.from_cache == 1


def test_repaired_partial_summary_does_not_count_as_complete():
    from mailcheck.llm.schema import parse_results
    results = parse_results('{"results":[{"id":"0","category":"application_ack","confidence":0.95,"action_required":false,"summary":"We rece')
    assert results['0'].response_complete is False


def test_completed_item_survives_later_partial_summary():
    from mailcheck.llm.schema import parse_results
    results = parse_results('{"results":[{"id":"0","category":"application_ack","confidence":0.95,"action_required":false,"summary":"Application received."},{"id":"1","category":"interview_invite","confidence":0.95,"action_required":true,"summary":"Please sch')
    assert results['0'].response_complete is True
    assert results['1'].response_complete is False


def test_short_decision_does_not_inherit_old_invitation():
    msg = message('Update', 'We decided not to proceed.\nOn Monday Sam wrote:\n> Please schedule your interview.')
    assert 'schedule your interview' not in msg.body


def test_explicit_uncertainty_is_retried_then_reviewed():
    client = Replies([{'id': str(i), 'category': 'other', 'confidence': .9,
                      'needs_review': True, 'action_required': False, 'summary': 'Ambiguous scheduling update.'}
                      for i in (0, 1, 1)])
    result, _ = classify(client, [message('Update', 'Can we talk tomorrow?')])
    assert result[0].category == 'unclassified'


def test_evaluation_reports_receipt_precision_and_missed_interviews():
    from types import SimpleNamespace
    from tools.evaluate_classification import metrics
    expected = [{'category': 'interview_invite', 'action_required': True},
                {'category': 'application_ack', 'action_required': False},
                {'category': 'job_alert', 'action_required': False}]
    actual = [SimpleNamespace(category='other', action_required=False),
              SimpleNamespace(category='application_ack', action_required=False),
              SimpleNamespace(category='application_ack', action_required=False)]
    measured = metrics(expected, actual)
    assert measured['interview_invite']['recall'] == 0
    assert measured['application_ack']['precision'] == .5
    assert measured['application_ack']['recall'] == 1
    assert measured['important_sent_to_noise'] == 1


def test_short_substantive_message_is_not_assumed_to_need_old_quote():
    msg = message('Update', 'Congratulations, welcome aboard!\nOn Monday Sam wrote:\n> Please schedule your interview.')
    assert 'schedule your interview' not in msg.body
