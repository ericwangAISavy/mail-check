"""The job work queue: To do, Completed and Expired derive from when a row first
held a job and from its check cell; nothing else is stored."""

import time
import unittest
from tests import test_native_sourcing as base

DAY = 24 * 3600


class SourcingLifecycleTests(unittest.TestCase):
    setUp = base.NativeSheetTests.setUp
    tab = base.NativeSheetTests.tab
    snapshot = base.NativeSheetTests.snapshot

    def columns(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        return {c['kind']: c['id'] for c in snapshot['columns']}

    def add(self, rows, work_date='2026-10-20'):
        base = self.snapshot()
        return self.native.append(self.conn, self.tab(), f'append-{time.time_ns()}', base['revision'], rows, work_date=work_date)

    def created(self, row_id):
        return self.conn.execute('SELECT created_at FROM native_rows WHERE id=?', (row_id,)).fetchone()[0]

    def set_created(self, row_id, stamp):
        self.conn.execute('UPDATE native_rows SET created_at=? WHERE id=?', (stamp, row_id)); self.conn.commit()

    def check(self, row_id):
        snap = self.snapshot()
        column = self.columns(snap)['check']
        index = snap['row_ids'].index(row_id)
        version = snap['rows'][index][[c['id'] for c in snap['columns']].index(column)]['version']
        self.native.save(self.conn, self.tab(), f'check-{time.time_ns()}', [{'row_id': row_id, 'column_id': column, 'expected_version': version, 'value': 'true'}])

    def queue(self, now=None):
        return self.native.workload(self.conn, [self.tab_id], now)[self.tab_id]

    def test_new_jobs_are_stamped_once_and_blank_rows_are_not(self):
        before = time.time()
        result = self.add([['Acme', 'Engineer', 'https://jobs.test/1']])
        row = result['row_ids'][1]
        self.assertGreaterEqual(self.created(row), before)
        blanks = self.conn.execute("SELECT COUNT(*) FROM native_rows WHERE tab_id=? AND created_at IS NOT NULL", (self.tab_id,)).fetchone()[0]
        self.assertEqual(blanks, 1)

    def test_editing_checking_and_moving_never_reset_the_window(self):
        row = self.add([['Acme', 'Engineer', 'https://jobs.test/1']])['row_ids'][1]
        self.set_created(row, 1000.0)
        snap = self.snapshot(); cols = self.columns(snap); index = snap['row_ids'].index(row)
        version = snap['rows'][index][[c['id'] for c in snap['columns']].index(cols['role'])]['version']
        self.native.save(self.conn, self.tab(), 'edit-role', [{'row_id': row, 'column_id': cols['role'], 'expected_version': version, 'value': 'Staff Engineer'}])
        self.assertEqual(self.created(row), 1000.0)
        self.native.structure(self.conn, self.tab(), 'move', self.snapshot()['revision'], {'action': 'move_date', 'ids': [row], 'work_date': '2026-10-25'})
        self.assertEqual(self.created(row), 1000.0)
        self.check(row)
        self.assertEqual(self.created(row), 1000.0)

    def test_status_boundaries_and_counts(self):
        rows = self.add([['A', 'R', 'https://j/1'], ['B', 'R', 'https://j/2'], ['C', 'R', 'https://j/3'], ['D', 'R', 'https://j/4']])['row_ids'][1:5]
        now = 2_000_000_000.0
        day_start = self.native.today_start(now)
        self.set_created(rows[0], max(day_start + 60, now - 3600))     # new today
        self.set_created(rows[1], now - 6 * DAY)                        # carryover, expiring soon (24h left)
        self.set_created(rows[2], now - 7 * DAY)                        # exactly 168h: expired
        self.set_created(rows[3], now - 30 * DAY)                       # old but completed
        self.check(rows[3])
        q = self.queue(now)
        self.assertEqual(q['todo'], 2)
        self.assertEqual(q['new_today'] + q['carryover'], q['todo'])
        self.assertEqual(q['new_today'], 1)
        self.assertEqual(q['expiring'], 1)
        self.assertEqual(q['expired'], 1)
        self.assertEqual(q['completed'], 1)
        self.assertEqual(q['all'], 4)

    def test_expiring_soon_window_is_exactly_48_hours(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        now = 2_000_000_000.0
        cases = [(now - 5 * DAY + 1, 0, 1),    # 48h + 1s left: still ordinary To do
                 (now - 5 * DAY, 1, 1),        # exactly 48h left: expiring soon
                 (now - 5 * DAY - 1, 1, 1),    # 48h - 1s left: expiring soon
                 (now - 7 * DAY, 0, 0)]        # 168h old: expired, so no longer To do
        for created, expiring, todo in cases:
            self.set_created(row, created)
            q = self.queue(now)
            self.assertEqual((q['expiring'], q['todo']), (expiring, todo), created)

    def test_completed_jobs_never_expire(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        self.set_created(row, 0.0)
        self.check(row)
        q = self.queue()
        self.assertEqual((q['completed'], q['expired'], q['todo']), (1, 0, 0))

    def test_emptied_row_forgets_its_stamp(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        snap = self.snapshot(); cols = self.columns(snap); index = snap['row_ids'].index(row)
        ids = [c['id'] for c in snap['columns']]
        changes = [{'row_id': row, 'column_id': cols[k], 'expected_version': snap['rows'][index][ids.index(cols[k])]['version'], 'value': ''} for k in ('company', 'role', 'link')]
        self.native.save(self.conn, self.tab(), 'clear', changes)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM native_rows WHERE tab_id=? AND created_at IS NOT NULL", (self.tab_id,)).fetchone()[0], 0)

    def test_assign_date_dates_only_new_jobs_and_never_rejects_older_rows(self):
        old = self.add([['Old', 'R', 'https://j/1']], work_date='2026-10-01')['row_ids'][1]
        snap = self.snapshot(); cols = self.columns(snap); ids = [c['id'] for c in snap['columns']]
        blank = next(r for r, d in zip(snap['row_ids'][1:], snap['row_dates'][1:]) if d is None)
        old_index = snap['row_ids'].index(old); blank_index = snap['row_ids'].index(blank)
        self.native.save(self.conn, self.tab(), 'queue-edit', [
            {'row_id': old, 'column_id': cols['role'], 'expected_version': snap['rows'][old_index][ids.index(cols['role'])]['version'], 'value': 'Edited'},
            {'row_id': blank, 'column_id': cols['company'], 'expected_version': snap['rows'][blank_index][ids.index(cols['company'])]['version'], 'value': 'New Co'},
        ], assign_date='2026-11-26')
        dates = dict(self.conn.execute('SELECT id,work_date FROM native_rows WHERE id IN (?,?)', (old, blank)).fetchall())
        self.assertEqual(dates, {old: '2026-10-01', blank: '2026-11-26'})
        with self.assertRaises(ValueError):
            self.native.save(self.conn, self.tab(), 'bad', [{'row_id': old, 'column_id': cols['role'], 'expected_version': 99, 'value': 'x'}], work_date='2026-10-01', assign_date='2026-11-26')

    def test_backfill_uses_sourcing_day_start_and_keeps_existing_stamps(self):
        rows = self.add([['A', 'R', 'https://j/1'], ['B', 'R', 'https://j/2']], work_date='2026-10-20')['row_ids'][1:3]
        self.conn.execute('UPDATE native_rows SET created_at=NULL WHERE id=?', (rows[0],))
        self.set_created(rows[1], 123.0)
        self.native.backfill_created(self.conn); self.conn.commit()
        from datetime import date
        self.assertEqual(self.created(rows[0]), self.native._day_start(date(2026, 10, 20)))
        self.assertEqual(self.created(rows[1]), 123.0)

    def test_snapshot_and_index_carry_lifecycle_data(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        snap = self.snapshot()
        self.assertEqual(len(snap['row_created']), len(snap['row_ids']))
        self.assertIsNotNone(snap['row_created'][snap['row_ids'].index(row)])
        self.assertEqual(snap, self.snapshot())  # unchanged sheet, identical snapshot
        response = self.client.get('/api/sourcing')
        self.assertEqual(response.status_code, 200, response.text)
        tab = next(t for b in response.json()['books'] for t in b['tabs'] if t['id'] == self.tab_id)
        self.assertEqual(tab['queue']['todo'], 1)
        book = next(b for b in response.json()['books'] if any(t['id'] == self.tab_id for t in b['tabs']))
        self.assertEqual(book['queue']['todo'], 1)



class SourcingLifecycleReuseTests(unittest.TestCase):
    setUp = SourcingLifecycleTests.setUp
    tab, snapshot, columns, add = SourcingLifecycleTests.tab, SourcingLifecycleTests.snapshot, SourcingLifecycleTests.columns, SourcingLifecycleTests.add
    created, set_created = SourcingLifecycleTests.created, SourcingLifecycleTests.set_created

    def test_a_cleared_row_reused_for_a_new_job_starts_a_new_window(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        self.set_created(row, 1000.0)
        snap = self.snapshot(); cols = self.columns(snap); ids = [c['id'] for c in snap['columns']]; index = snap['row_ids'].index(row)
        self.native.save(self.conn, self.tab(), 'clear-row', [{'row_id': row, 'column_id': cols[k], 'expected_version': snap['rows'][index][ids.index(cols[k])]['version'], 'value': ''} for k in ('company', 'role', 'link')])
        stale = self.conn.execute("SELECT COUNT(*) FROM native_rows WHERE tab_id=? AND created_at=1000.0", (self.tab_id,)).fetchone()[0]
        self.assertEqual(stale, 0)
        snap = self.snapshot(); ids = [c['id'] for c in snap['columns']]
        blank = next(r for r, created in zip(snap['row_ids'][1:], snap['row_created'][1:]) if created is None)
        index = snap['row_ids'].index(blank)
        before = time.time()
        self.native.save(self.conn, self.tab(), 'reuse-row', [{'row_id': blank, 'column_id': cols['company'], 'expected_version': snap['rows'][index][ids.index(cols['company'])]['version'], 'value': 'New Co'}])
        self.assertGreaterEqual(self.created(blank), before)

    def test_structural_operations_forget_stamps_of_rows_left_blank(self):
        row = self.add([['A', 'R', 'https://j/1']])['row_ids'][1]
        self.conn.execute('DELETE FROM native_cells WHERE row_id=?', (row,))  # emptied outside a save
        self.native.sync_created(self.conn, self.tab_id)
        self.assertIsNotNone(self.created(row))  # an ordinary save does not scan the sheet
        self.native.sync_created(self.conn, self.tab_id, clear=True)
        self.assertIsNone(self.created(row))


if __name__ == '__main__':
    unittest.main()
