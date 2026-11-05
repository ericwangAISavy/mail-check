import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tools.recover_application_checks import recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'db.sqlite'
        self.config = self.root/'config.toml'
        self.config.write_text('')
        self.audit = self.root/'audit.json'
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
          CREATE TABLE bidders(id INTEGER,name TEXT,removed_at TEXT);
          CREATE TABLE native_books(id INTEGER,bidder_id INTEGER);
          CREATE TABLE native_tabs(id INTEGER,book_id INTEGER,account_id INTEGER,revision INTEGER,updated_at REAL);
          CREATE TABLE native_rows(id TEXT,tab_id INTEGER,work_date TEXT);
          CREATE TABLE native_columns(id INTEGER,tab_id INTEGER,kind TEXT);
          CREATE TABLE native_cells(row_id TEXT,column_id INTEGER,value TEXT,version INTEGER DEFAULT 0,UNIQUE(row_id,column_id));
          CREATE TABLE sourcing_check_activity(row_id TEXT,source TEXT,confirmed_at TEXT,message_id TEXT);
          CREATE TABLE bidder_assignments(bidder_id INTEGER,account_id INTEGER,start_date TEXT,end_date TEXT);
          INSERT INTO bidders VALUES(1,'Alex',NULL);
          INSERT INTO native_books VALUES(1,1);
          INSERT INTO native_tabs VALUES(1,1,2,4,0);
          INSERT INTO native_rows VALUES('row',1,'2026-11-02');
          INSERT INTO native_columns VALUES(1,1,'check'),(2,1,'link');
          INSERT INTO native_cells VALUES('row',1,'false',0),('row',2,'https://example.test/job',0);
          INSERT INTO sourcing_check_activity VALUES('row','rebuild-cleared',NULL,NULL);
          INSERT INTO bidder_assignments VALUES(1,2,'2026-11-01',NULL);
        ''')
        self.audit.write_text(json.dumps({'week_start':'2026-11-02','diagnostics':[
            {'row_id':'row','bidder_id':1,'account_id':2,'work_date':'2026-11-02',
             'reasons':['previous_automatic_check_cleared_by_rebuild']}]}))

    def test_preview_does_not_write_and_apply_is_idempotent(self):
        before = self.path.read_bytes()
        self.assertEqual(recover(self.path,self.audit)['restore_count'],1)
        self.assertEqual(before,self.path.read_bytes())
        result = recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)
        self.assertEqual(result['restore_count'],1)
        self.assertEqual(self.conn.execute('SELECT value,version FROM native_cells WHERE column_id=1').fetchone(),('true',1))
        self.assertEqual(self.conn.execute('SELECT source,confirmed_at,message_id FROM sourcing_check_activity').fetchone(),('recovered-rebuild',None,None))
        self.assertEqual(self.conn.execute('SELECT revision FROM native_tabs').fetchone()[0],5)
        self.assertEqual(recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)['restore_count'],0)
        self.assertEqual(self.conn.execute('SELECT revision FROM native_tabs').fetchone()[0],5)

    def test_conflicts_abort_all_changes(self):
        self.conn.execute("UPDATE native_rows SET work_date='2026-11-03'")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError,'conflicts'):
            recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)
        self.assertEqual(self.conn.execute('SELECT value FROM native_cells WHERE column_id=1').fetchone()[0],'false')

    def test_apply_requires_explicit_date_policy(self):
        with self.assertRaisesRegex(ValueError,'use-source-dates'):
            recover(self.path,self.audit,apply=True,config=self.config)

    def test_live_receipt_proof_blocks_restore(self):
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-11-03T12:00:00+00:00'")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError,'conflicts'):
            recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)

    def test_active_installation_lock_blocks_apply(self):
        from mailcheck.maintenance import MaintenanceLock, MaintenanceBusyError, lock_path
        with MaintenanceLock(lock_path(self.config)):
            with self.assertRaises(MaintenanceBusyError):
                recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)
        self.assertEqual(self.conn.execute('SELECT value FROM native_cells WHERE column_id=1').fetchone()[0],'false')

    def test_one_conflict_prevents_other_valid_targets_being_restored(self):
        document = json.loads(self.audit.read_text())
        document['diagnostics'].append(dict(document['diagnostics'][0],row_id='missing'))
        self.audit.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError,'conflicts'):
            recover(self.path,self.audit,apply=True,use_source_dates=True,config=self.config)
        self.assertEqual(self.conn.execute('SELECT value FROM native_cells WHERE column_id=1').fetchone()[0],'false')
