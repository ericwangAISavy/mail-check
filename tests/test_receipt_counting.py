import sqlite3
import unittest
from datetime import date

from mailcheck import receipt_counting as rc


class ReceiptCountingTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript('''
        CREATE TABLE application_receipts(account_id, message_id, received_at, category, company, role, sender, duplicate_of, counting_evidence);
        CREATE TABLE messages(account_id,message_id,body_text,interview_text);
        CREATE TABLE native_rows(id,tab_id,work_date);
        CREATE TABLE native_tabs(id,book_id,account_id,archived);
        CREATE TABLE native_books(id,bidder_id);
        CREATE TABLE native_columns(id,tab_id,kind);
        CREATE TABLE native_cells(row_id,column_id,value);
        CREATE TABLE sourcing_check_activity(row_id,message_id,confirmed_at);
        CREATE TABLE bidder_assignments(bidder_id,account_id,start_date,end_date);
        INSERT INTO native_books VALUES(1,1);
        INSERT INTO native_tabs VALUES(1,1,1,0);
        INSERT INTO bidder_assignments VALUES(1,1,'2026-01-01',NULL);
        INSERT INTO native_columns VALUES('c',1,'company'),('r',1,'role'),('l',1,'link'),('x',1,'check');
        ''')
        self.receipt('p', 'noreply@indeed.com')
        self.receipt('e', 'hr@acme.test')
        self.job('j')

    def receipt(self, key, sender, account=1, stamp='2026-11-02T16:00:00Z'):
        self.c.execute('INSERT INTO application_receipts VALUES(?,?,?,\'application_ack\',\'Acme\',\'C++ Developer 2\',?,NULL,\'\')', (account,key,stamp,sender))

    def job(self, key):
        self.c.execute('INSERT INTO native_rows VALUES(?,1,\'2026-11-02\')',(key,))
        for col,value in [('c','Acme'),('r','C++ Developer 2'),('l','https://jobs.test/'+key),('x','true')]:
            self.c.execute('INSERT INTO native_cells VALUES(?,?,?)',(key,col,value))
        self.c.execute('INSERT INTO sourcing_check_activity VALUES(?,\'e\',\'2026-11-02T16:00:00Z\')',(key,))

    def rows(self):
        return rc.effective_receipts(self.c,date(2026,11,2),date(2026,11,3))

    def counted(self):
        return sum(not r['duplicate_of'] for r in self.rows())

    def test_proven_pair_read_only_and_materialization_idempotent(self):
        before=self.c.total_changes
        self.assertEqual((len(self.rows()),self.counted()),(2,1))
        self.assertEqual(self.c.total_changes,before)
        self.assertEqual(rc.materialize(self.c,date(2026,11,2),date(2026,11,3)),1)
        self.assertEqual(rc.materialize(self.c,date(2026,11,2),date(2026,11,3)),0)

    def test_platform_only(self):
        self.c.execute("DELETE FROM application_receipts WHERE message_id='e'")
        self.assertEqual(self.counted(),1)

    def test_two_jobs_never_merge(self):
        self.job('j2')
        self.assertEqual(self.counted(),2)

    def test_future_job_blocks_merge(self):
        self.job('j2')
        self.c.execute("UPDATE native_rows SET work_date='2027-01-01' WHERE id='j2'")
        self.assertEqual(self.counted(),2)

    def test_cross_account_and_day(self):
        for field,value in [('account_id',2),('received_at','2026-11-03T16:00:00Z')]:
            with self.subTest(field=field):
                self.c.execute('SAVEPOINT trial')
                self.c.execute(f"UPDATE application_receipts SET {field}=? WHERE message_id='e'",(value,))
                self.assertEqual(self.counted(),2)
                self.c.execute('ROLLBACK TO trial')

    def test_missing_metadata_and_multiple_employers(self):
        self.receipt('e2','jobs@acme.test')
        self.assertEqual(self.counted(),3)
        self.c.execute("DELETE FROM application_receipts WHERE message_id='e2'")
        self.c.execute("UPDATE application_receipts SET role='' WHERE message_id='p'")
        self.assertEqual(self.counted(),2)

    def test_conflicting_application_references(self):
        self.c.executemany('INSERT INTO messages VALUES(1,?,?,NULL)', [('p','Application ID: ABC-123'),('e','Application ref: ABC-456')])
        self.assertEqual(self.counted(),2)
        self.assertIsNone(rc.application_reference('Job ID: 1234'))
        self.assertIsNone(rc.application_reference('application id thanks'))

    def test_durable_proof_and_reclassification(self):
        rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
        self.c.execute('DELETE FROM messages')
        self.c.execute('DELETE FROM native_rows')
        self.assertEqual(self.counted(),1)
        self.c.execute("UPDATE application_receipts SET category='other' WHERE message_id='e'")
        self.assertEqual(self.counted(),1)
        rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
        self.assertIsNone(self.c.execute("SELECT duplicate_of FROM application_receipts WHERE message_id='p'").fetchone()[0])

    def test_metadata_punctuation_is_significant(self):
        self.c.execute("UPDATE application_receipts SET role='C Developer 2' WHERE message_id='e'")
        self.assertEqual(self.counted(),2)

    def test_durable_proof_invalidated_by_origin_metadata_and_orphan(self):
        for statement in ["UPDATE application_receipts SET sender='other@acme.test' WHERE message_id='e'",
                          "UPDATE application_receipts SET role='C# Developer 2' WHERE message_id='e'",
                          "DELETE FROM application_receipts WHERE message_id='e'",
                          "UPDATE application_receipts SET category='other' WHERE message_id='p'"]:
            with self.subTest(statement=statement):
                self.c.execute('SAVEPOINT trial')
                rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
                self.c.execute('DELETE FROM native_rows')
                self.c.execute(statement)
                self.assertFalse(any(r['duplicate_of'] for r in self.rows()))
                rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
                self.assertFalse(any(r[0] for r in self.c.execute('SELECT duplicate_of FROM application_receipts')))
                self.c.execute('ROLLBACK TO trial')

    def test_invalid_claim_or_assignment_does_not_prove_pair(self):
        for statement in ["UPDATE sourcing_check_activity SET message_id='unknown'",
                          "UPDATE sourcing_check_activity SET confirmed_at='2026-11-03T16:00:00Z'",
                          "UPDATE native_cells SET value='' WHERE column_id='l'",
                          "UPDATE native_cells SET value='false' WHERE column_id='x'",
                          "UPDATE bidder_assignments SET end_date='2026-11-01'"]:
            with self.subTest(statement=statement):
                self.c.execute('SAVEPOINT trial')
                self.c.execute(statement)
                self.assertEqual(self.counted(),2)
                self.c.execute('ROLLBACK TO trial')

    def test_real_application_schema_empty_query(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from mailcheck import db, config
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            with patch.object(config, 'config_dir', return_value=Path(directory)):
                c = db.connect(Path(directory)/'mail.db')
            try:
                self.assertEqual(rc._jobs(c,1,date(2026,11,2)),[])
                self.assertEqual(rc.effective_receipts(c,date(2026,11,2),date(2026,11,3)),[])
                self.assertEqual(rc.materialize(c,date(2026,11,2),date(2026,11,3)),0)
            finally:
                c.close()

    def test_naive_utc_receipts_and_claims_match_chicago_day(self):
        self.c.execute("UPDATE application_receipts SET received_at='2026-11-02T16:00:00'")
        self.c.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-11-02T16:00:00'")
        self.assertEqual((len(self.rows()),self.counted()),(2,1))
        self.c.execute("UPDATE application_receipts SET received_at='2026-11-02T05:59:59'")
        self.assertEqual(self.rows(),[])

    def test_safe_seniority_and_unicode_aliases(self):
        for short,long in [('Sr. C++ Developer 2','Senior C++ Developer 2'),
                           ('Jr C# Developer 2','Junior C# Developer 2'),
                           ('Ｓｒ． C++ Developer 2','Senior C++ Developer 2')]:
            with self.subTest(short=short):
                self.c.execute("UPDATE application_receipts SET role=? WHERE message_id='p'",(short,))
                self.c.execute("UPDATE application_receipts SET role=? WHERE message_id='e'",(long,))
                self.c.execute("UPDATE native_cells SET value=? WHERE column_id='r'",(long,))
                self.assertEqual(self.counted(),1)

    def test_multiple_explicit_refs_in_one_body_block_pair(self):
        self.c.execute("INSERT INTO messages VALUES(1,'p','Application ID: 123; Application ID: 456',NULL)")
        self.assertIsNone(rc.application_reference('Application ID: 123; Application ID: 456'))
        self.assertEqual(self.counted(),2)

    def test_day_source_cache_shared_across_metadata_groups(self):
        from unittest.mock import patch
        self.receipt('p2','noreply@indeed.com')
        self.receipt('e2','hr@other.test')
        self.c.execute("UPDATE application_receipts SET company='Other' WHERE message_id IN ('p2','e2')")
        with patch.object(rc,'_jobs',wraps=rc._jobs) as jobs:
            self.rows()
            self.assertEqual(jobs.call_count,1)

    def test_persisted_proof_revoked_by_new_live_job(self):
        rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
        self.job('second-job')
        self.assertEqual(self.counted(),2)

    def test_persisted_proof_revoked_by_changed_source(self):
        for statement in ["UPDATE native_cells SET value='false' WHERE column_id='x'",
                          "UPDATE native_cells SET value='https://changed.test/job' WHERE column_id='l'",
                          "UPDATE native_cells SET value='Other' WHERE column_id='c'",
                          "UPDATE sourcing_check_activity SET message_id='unknown'",
                          "UPDATE native_rows SET work_date='2025-01-01'",
                          "UPDATE bidder_assignments SET end_date='2026-11-01'"]:
            with self.subTest(statement=statement):
                self.c.execute('SAVEPOINT trial')
                rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
                self.c.execute(statement)
                self.assertEqual(self.counted(),2)
                self.c.execute('ROLLBACK TO trial')

    def test_alphabetic_explicit_references_conflict(self):
        self.assertEqual(rc.application_reference('Application ID: ABC'),'abc')
        self.assertIsNone(rc.application_reference('application id thanks'))
        self.c.executemany('INSERT INTO messages VALUES(1,?,?,NULL)',
                           [('p','Application ID: ABC'),('e','Application ID: DEF')])
        self.assertEqual(self.counted(),2)

    def test_pruned_proof_revoked_by_replacement_job(self):
        rc.materialize(self.c,date(2026,11,2),date(2026,11,3))
        self.c.execute('DELETE FROM native_rows')
        self.job('replacement')
        self.assertEqual(self.counted(),2)

    def test_multiple_alphabetic_refs_in_one_body_block_pair(self):
        self.c.execute("INSERT INTO messages VALUES(1,'p','Application ID: ABC; Application reference=DEF',NULL)")
        self.assertEqual(self.counted(),2)
