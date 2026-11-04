"""Synthetic-only classification evaluation; never opens a mailbox or database.

Run against the same Ollama endpoint/model before and after a change. Use
--source-root to evaluate a detached baseline checkout with this same corpus.
An accuracy score is only meaningful after live inference, not --validate-only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone


def metrics(expected, results):
    out = {}
    for category in ('interview_invite', 'application_ack'):
        tp = sum(e['category'] == r.category == category for e, r in zip(expected, results))
        actual = sum(e['category'] == category for e in expected)
        predicted = sum(r.category == category for r in results)
        out[category] = {'precision': tp / predicted if predicted else None,
                         'recall': tp / actual if actual else None,
                         'expected': actual, 'predicted': predicted}
    important = {'interview_invite', 'application_ack', 'assessment', 'offer', 'info_request', 'rejection'}
    out['important_sent_to_noise'] = sum(e['category'] in important and r.category in {'job_alert', 'other'}
                                        for e, r in zip(expected, results))
    out['manual_review_count'] = sum(r.category == 'unclassified' for r in results)
    out['action_accuracy'] = sum(e['action_required'] == r.action_required for e, r in zip(expected, results)) / len(expected)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--corpus', type=Path, default=Path(__file__).with_name('classification_cases.json'))
    parser.add_argument('--base-url')
    parser.add_argument('--model', default='')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from mailcheck.normalize import normalize
    from mailcheck.prefilter import apply
    from mailcheck.models import RawMessage
    from mailcheck.taxonomy import MODEL_CATEGORIES
    from mailcheck.llm import LLMClient, classify, PROMPT_VERSION
    cases = json.loads(args.corpus.read_text())
    assert len({c['id'] for c in cases}) == len(cases)
    assert all(c['category'] in MODEL_CATEGORIES and isinstance(c['action_required'], bool) for c in cases)
    messages = [normalize(RawMessage(c['id'], str(i), 'INBOX', c.get('sender', 'recruiter@example.test'),
                    'Synthetic sender', c['subject'], datetime(2026, 11, 4, tzinfo=timezone.utc),
                    c['body'], calendar_data=c.get('calendar_data', [])),
                    account_id=0, account_label='synthetic') for i, c in enumerate(cases)]
    if PROMPT_VERSION != "1":
        assert all(len(m.body) <= 1200 for m in messages)
    if args.validate_only:
        print(json.dumps({'cases_validated': len(cases), 'live_inference': False}))
        return
    if not args.base_url:
        parser.error('--base-url is required for live evaluation')
    started = time.monotonic()
    results = [apply(m) for m in messages]
    pending = [i for i, r in enumerate(results) if r is None]
    events = []
    with LLMClient(base_url=args.base_url, model=args.model) as client:
        model = client.resolve_model()
        classified, errors = classify(client, [messages[i] for i in pending], event=events.append)
    for i, result in zip(pending, classified):
        results[i] = result
    requests = sum(e['type'] == 'llm_request' for e in events)
    print(json.dumps({'prompt_version': PROMPT_VERSION, 'model': model,
        'cases': len(cases), 'elapsed_seconds': time.monotonic() - started,
        'requests_per_message': requests / len(cases), 'errors': errors,
        'metrics': metrics(cases, results),
        'results': [{'id': c['id'], 'expected': c['category'], 'actual': r.category,
                     'action_required': r.action_required} for c, r in zip(cases, results)]}, indent=2))


if __name__ == '__main__':
    main()
