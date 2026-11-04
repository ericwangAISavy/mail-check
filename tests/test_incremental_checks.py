"""Checkpoint mail collection resumes safely without moving failed accounts."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from mailcheck import db, pipeline, mail_checkpoints as checkpoints
from mailcheck.config import Config
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.sources.base import SourceError
from tests import test_frontend_api as fixtures


class IncrementalCheckTests(unittest.TestCase):
    setUp = fixtures.FrontendApiTests.setUp

    def cfg(self):
        return Config(check={"mode": "since_last"})

    def run_check(self, fetch, cfg=None, **kwargs):
        with patch.object(pipeline, "fetch_account", side_effect=fetch), \
             patch.object(pipeline.interviews, "process_run"), \
             patch.object(pipeline.prefilter, "apply", return_value=Classification(category="application_ack")):
            return pipeline.check_once(self.conn, cfg or self.cfg(), **kwargs)

    def test_first_check_falls_back_and_empty_success_is_saved_across_connections(self):
        before = datetime.now(timezone.utc)
        calls = []
        result = self.run_check(lambda account, since, cfg: calls.append(since) or [])
        self.assertEqual(result.accounts_checked, 1)
        self.assertEqual(calls, [(before - timedelta(days=2)).date()])
        account = db.get_account(self.conn, "personal")
        saved = checkpoints.checkpoint(self.conn, account)
        self.assertGreaterEqual(saved, before)
        self.assertLessEqual(saved, datetime.now(timezone.utc))
        with db.session(self.path) as other:
            self.assertEqual(checkpoints.checkpoint(other, account), saved)

    def test_next_check_uses_prior_start_with_overlap_and_explicit_days_override(self):
        account = db.get_account(self.conn, "personal")
        old = datetime.now(timezone.utc) - timedelta(days=4)
        checkpoints.record(self.conn, account, old); self.conn.commit()
        calls = []
        self.run_check(lambda account, since, cfg: calls.append(since) or [])
        self.assertEqual(calls[0], old - checkpoints.OVERLAP)
        calls.clear()
        self.run_check(lambda account, since, cfg: calls.append(since) or [], since_days=7)
        self.assertEqual(calls[0], (datetime.now(timezone.utc) - timedelta(days=7)).date())

    def test_failed_account_does_not_advance_while_healthy_account_does(self):
        second = db.add_account(self.conn, label="second", email="other@example.test")
        old = datetime.now(timezone.utc) - timedelta(days=3)
        account = db.get_account(self.conn, "personal")
        checkpoints.record(self.conn, account, old); self.conn.commit()
        def fetch(account, since, cfg):
            if account.label == "personal": raise SourceError("Offline")
            return []
        result = self.run_check(fetch)
        self.assertEqual(result.accounts_checked, 1)
        self.assertEqual(checkpoints.checkpoint(self.conn, account), old)
        self.assertIsNotNone(checkpoints.checkpoint(self.conn, db.get_account(self.conn, "second")))

    def test_mailbox_changes_and_future_checkpoints_fall_back(self):
        account = db.get_account(self.conn, "personal")
        checkpoints.record(self.conn, account, datetime.now(timezone.utc) + timedelta(days=1))
        self.assertIsNone(checkpoints.checkpoint(self.conn, account))
        self.conn.execute("UPDATE accounts SET folder='Other' WHERE id=?", (account.id,))
        self.assertIsNone(checkpoints.checkpoint(self.conn, db.get_account(self.conn, "personal")))

    def test_failed_classification_preserves_checkpoint_and_persisted_mail(self):
        account = db.get_account(self.conn, "personal")
        old = datetime.now(timezone.utc) - timedelta(days=1)
        checkpoints.record(self.conn, account, old); self.conn.commit()
        message = NormalizedMessage(account.id, account.label, "<one@test>", "1", "INBOX",
                                    "from@test", "Sender", "Subject", datetime.now(timezone.utc), "Body")
        with patch.object(pipeline, "fetch_account", return_value=[message]), \
             patch.object(pipeline.prefilter, "apply", return_value=Classification(category="unclassified", retryable=True)), \
             patch.object(pipeline.interviews, "process_run"):
            pipeline.check_once(self.conn, self.cfg())
        self.assertEqual(checkpoints.checkpoint(self.conn, account), old)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

    def test_fixed_window_remains_default_and_records_success(self):
        calls = []
        self.run_check(lambda account, since, cfg: calls.append(since) or [], cfg=Config())
        self.assertEqual(calls[0], (datetime.now(timezone.utc) - timedelta(days=2)).date())
        self.assertIsNotNone(checkpoints.checkpoint(self.conn, db.get_account(self.conn, "personal")))

    def test_check_mode_is_saved_and_accounts_expose_last_success(self):
        response = self.client.post("/api/settings", json={"check_mode": "since_last"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/settings").json()["settings"]["check"]["mode"], "since_last")
        self.run_check(lambda *args: [])
        self.assertIsNotNone(self.client.get("/api/accounts").json()["accounts"][0]["last_checked_at"])
        self.assertEqual(self.client.post("/api/settings", json={"check_mode": "bad"}).status_code, 422)

    def test_failed_first_check_anchors_fallback_instead_of_sliding_forward(self):
        def failed(*args): raise SourceError("Offline")
        self.run_check(failed)
        account = db.get_account(self.conn, "personal")
        self.assertIsNone(checkpoints.checkpoint(self.conn, account))
        old = datetime.now(timezone.utc) - timedelta(days=12)
        self.conn.execute("UPDATE mail_checkpoints SET pending_since=?", (old.isoformat(),))
        self.conn.commit()
        calls = []
        self.run_check(lambda account, since, cfg: calls.append(since) or [])
        self.assertEqual(calls[0], old)

    def test_nonretryable_manual_review_does_not_stall_future_checks(self):
        account = db.get_account(self.conn, "personal")
        old = datetime.now(timezone.utc) - timedelta(days=1)
        checkpoints.record(self.conn, account, old); self.conn.commit()
        message = NormalizedMessage(account.id, account.label, "<review@test>", "1", "INBOX",
                                    "from@test", "Sender", "Subject", datetime.now(timezone.utc), "Body")
        with patch.object(pipeline, "fetch_account", return_value=[message]),              patch.object(pipeline.prefilter, "apply", return_value=Classification(category="unclassified")),              patch.object(pipeline.interviews, "process_run"):
            pipeline.check_once(self.conn, self.cfg())
        self.assertGreater(checkpoints.checkpoint(self.conn, account), old)

    def test_catchup_window_preserves_existing_done_state_past_retention(self):
        account = db.get_account(self.conn, "personal")
        old = datetime.now(timezone.utc) - timedelta(days=12)
        checkpoints.record(self.conn, account, old)
        message = NormalizedMessage(account.id, account.label, "<old@test>", "1", "INBOX",
                                    "from@test", "Sender", "Subject", old + timedelta(hours=1), "Body")
        pk = db.upsert_message(self.conn, message)
        self.conn.commit()
        db.set_handled(self.conn, pk, True)
        self.run_check(lambda *args: [message])
        self.assertIsNotNone(self.conn.execute("SELECT handled_at FROM messages WHERE id=?", (pk,)).fetchone()[0])

    def test_deferred_classification_only_holds_back_its_own_account(self):
        db.add_account(self.conn, label="second", email="other@example.test")
        accounts = db.list_accounts(self.conn)
        old = datetime.now(timezone.utc) - timedelta(days=1)
        for account in accounts: checkpoints.record(self.conn, account, old)
        self.conn.commit()
        def fetch(account, *args):
            return [NormalizedMessage(account.id, account.label, f"<{account.id}@test>", "1", "INBOX",
                                      "from@test", "Sender", "Subject", datetime.now(timezone.utc), "Body")]
        def classify(message, *args):
            return Classification(category="unclassified", retryable=True) if message.account_label == "personal" else Classification(category="application_ack")
        with patch.object(pipeline, "fetch_account", side_effect=fetch),              patch.object(pipeline.prefilter, "apply", side_effect=classify),              patch.object(pipeline.interviews, "process_run"):
            pipeline.check_once(self.conn, self.cfg())
        self.assertEqual(checkpoints.checkpoint(self.conn, accounts[0]), old)
        self.assertGreater(checkpoints.checkpoint(self.conn, accounts[1]), old)

    def test_upgrade_adds_checkpoints_without_changing_accounts(self):
        self.conn.execute("DROP TABLE mail_checkpoints")
        self.conn.execute("PRAGMA user_version=36")
        self.conn.commit()
        with db.session(self.path) as reopened:
            self.assertEqual(db.get_account(reopened, "personal").id, self.account_id)
            self.assertIsNone(checkpoints.checkpoint(reopened, db.get_account(reopened, "personal")))

    def test_overlapping_runs_cannot_move_success_time_backwards(self):
        account = db.get_account(self.conn, "personal")
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        checkpoints.record(self.conn, account, recent)
        checkpoints.record(self.conn, account, recent - timedelta(hours=1))
        self.assertEqual(checkpoints.checkpoint(self.conn, account), recent)

    def test_recently_collected_mail_with_old_sender_date_keeps_done_on_overlap(self):
        account = db.get_account(self.conn, "personal")
        previous = datetime.now(timezone.utc) - timedelta(minutes=1)
        checkpoints.record(self.conn, account, previous)
        message = NormalizedMessage(account.id, account.label, "<stale-date@test>", "1", "INBOX",
                                    "from@test", "Sender", "Subject", previous - timedelta(days=90), "Body")
        pk = db.upsert_message(self.conn, message); self.conn.commit()
        db.set_handled(self.conn, pk, True)
        self.run_check(lambda *args: [message])
        row = self.conn.execute("SELECT handled_at FROM messages WHERE id=?", (pk,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row[0])

    def test_narrow_explicit_override_does_not_skip_an_incremental_backlog(self):
        account = db.get_account(self.conn, "personal")
        old = datetime.now(timezone.utc) - timedelta(days=10)
        checkpoints.record(self.conn, account, old); self.conn.commit()
        self.run_check(lambda *args: [], since_days=1)
        self.assertEqual(checkpoints.checkpoint(self.conn, account), old)

    def test_widening_first_check_lookback_includes_the_requested_older_mail(self):
        account = db.get_account(self.conn, "personal")
        now = datetime.now(timezone.utc)
        checkpoints.begin(self.conn, account, (now-timedelta(days=2)).date())
        cfg = self.cfg()
        cfg.check.lookback_days = 10
        actual = checkpoints.window(self.conn, account, cfg.check, None, now)
        self.assertLessEqual(checkpoints.window_start(actual), checkpoints.window_start((now-timedelta(days=10)).date()))

    def test_checkpoint_snapshot_uses_one_query_for_many_accounts(self):
        accounts = [db.get_account(self.conn,"personal")]
        for i in range(12):
            db.add_account(self.conn,label=f"bulk-{i}",email=f"bulk-{i}@example.test")
        accounts = db.list_accounts(self.conn)
        stamp = datetime.now(timezone.utc)-timedelta(minutes=1)
        for account in accounts: checkpoints.record(self.conn,account,stamp)
        queries=[]
        self.conn.set_trace_callback(queries.append)
        try:
            values = checkpoints.snapshot(self.conn,accounts)
        finally:
            self.conn.set_trace_callback(None)
        self.assertEqual(set(values),{account.id for account in accounts})
        self.assertTrue(all(value==stamp for value in values.values()))
        self.assertEqual(len([sql for sql in queries if sql.lstrip().upper().startswith("SELECT")]),1)

    def test_inbox_only_checkpoint_is_reset_when_junk_coverage_is_enabled(self):
        import hashlib,json
        account=db.get_account(self.conn,"personal")
        legacy_key=hashlib.sha256(json.dumps([account.provider,account.email.casefold(),account.imap_host,account.imap_port,account.use_ssl,account.folder]).encode()).hexdigest()
        stamp=datetime.now(timezone.utc)-timedelta(minutes=1)
        self.conn.execute("INSERT INTO mail_checkpoints(account_id,mailbox,checked_at) VALUES(?,?,?)",(account.id,legacy_key,stamp.isoformat()))
        self.conn.commit()
        now=datetime.now(timezone.utc)
        self.assertEqual(checkpoints.window(self.conn,account,self.cfg().check,None,now),(now-timedelta(days=2)).date())
