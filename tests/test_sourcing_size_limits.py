"""Sheet display budgets do not prevent bounded CSV recovery."""
import csv
import io
from unittest.mock import patch

import pytest

from mailcheck import db, native_sourcing as sheets, sourcing_csv


@pytest.fixture
def sheet(tmp_path, monkeypatch):
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(tmp_path / 'maintenance.lock'))
    conn = db.connect(tmp_path / 'mail.db')
    account = db.add_account(conn, label='profile', email='profile@example.test')
    conn.execute("INSERT INTO bidders(name,created_at) VALUES('Bidder','2026-01-01')")
    conn.commit()
    book = sheets.create_book(conn, 1)
    tab_id = sheets.create_tab(conn, book, account, 'Jobs')
    try:
        yield conn, {'id': tab_id}
    finally:
        conn.close()


def test_wide_snapshot_rejected_before_loading_cells_but_csv_remains_available(sheet):
    conn, tab = sheet
    with sheets.atomic(conn):
        conn.executemany('INSERT INTO native_columns(id,tab_id,position,title) VALUES(?,?,?,?)',
                         [(sheets.new_id(), tab['id'], i, f'Extra{i}') for i in range(4, 101)])
        conn.executemany('INSERT INTO native_rows(id,tab_id,position) VALUES(?,?,?)',
                         [(sheets.new_id(), tab['id'], i) for i in range(100, 1000)])
        last_row = conn.execute('SELECT id FROM native_rows WHERE tab_id=? ORDER BY position DESC,id DESC LIMIT 1', (tab['id'],)).fetchone()[0]
        first_column = conn.execute('SELECT id FROM native_columns WHERE tab_id=? ORDER BY position,id LIMIT 1', (tab['id'],)).fetchone()[0]
        conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)', (last_row, first_column, 'Preserved job'))
    statements = []
    conn.set_trace_callback(statements.append)
    with pytest.raises(sheets.SnapshotTooLarge):
        sheets.snapshot(conn, tab)
    conn.set_trace_callback(None)
    assert not any('SELECT c.*' in sql for sql in statements)
    with patch.object(sheets, 'snapshot', side_effect=AssertionError('dense snapshot used')):
        rows = list(csv.reader(io.StringIO(sourcing_csv.export_rows(conn, tab))))
    assert len(rows) == 1001
    assert len(rows[0]) == 101
    assert rows[-1][0] == 'Preserved job'


def test_text_budget_rejects_before_loading_cells(sheet, monkeypatch):
    conn, tab = sheet
    row = conn.execute('SELECT id FROM native_rows WHERE tab_id=? LIMIT 1', (tab['id'],)).fetchone()[0]
    col = conn.execute('SELECT id FROM native_columns WHERE tab_id=? LIMIT 1', (tab['id'],)).fetchone()[0]
    conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)', (row,col,'é' * 20))
    conn.commit()
    monkeypatch.setattr(sheets, 'MAX_SNAPSHOT_BYTES', 30)
    with pytest.raises(sheets.SnapshotTooLarge, match='text'):
        sheets.snapshot(conn, tab)


def test_export_size_check_precedes_output_allocation(sheet, monkeypatch):
    conn, tab = sheet
    monkeypatch.setattr(sourcing_csv, 'MAX_EXPORT_BYTES', 1)
    with patch.object(sourcing_csv.io, 'StringIO', side_effect=AssertionError('allocated output')):
        with pytest.raises(sheets.SnapshotTooLarge, match='CSV export'):
            sourcing_csv.export_rows(conn, tab)
    assert not conn.in_transaction


@pytest.mark.parametrize('scope', ['all', 'undated', '2026-10-15', '2026-10-16'])
def test_sparse_export_matches_existing_csv_behavior(sheet, scope):
    conn, tab = sheet
    columns = conn.execute('SELECT id FROM native_columns WHERE tab_id=? ORDER BY position,id', (tab['id'],)).fetchall()
    rows = conn.execute('SELECT id FROM native_rows WHERE tab_id=? ORDER BY position,id', (tab['id'],)).fetchall()
    conn.execute("UPDATE native_columns SET title='Old custom title' WHERE id=?", (columns[0][0],))
    for index, (day, values) in enumerate([
        ('2026-10-15', ['=SUM(A1)', 'comma, quote"', 'https://jobs.test', 'false']),
        (None, ['', '', '', '']),
        ('2026-10-15', ['  +formula', 'é\nline', '', '']),
        ('2026-10-16', ['Last day', '', '', '']),
    ]):
        conn.execute('UPDATE native_rows SET work_date=? WHERE id=?', (day, rows[index][0]))
        for col, value in zip(columns, values):
            conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)', (rows[index][0],col[0],value))
    conn.commit()
    snapshot = sheets.snapshot(conn, tab)
    selected = [row for i, row in enumerate(snapshot['rows'])
                if i == 0 or scope == 'all' or snapshot['row_dates'][i] == (None if scope == 'undated' else scope)]
    while len(selected) > 1 and not any(cell['value'] for cell in selected[-1]):
        selected.pop()
    expected = io.StringIO(newline='')
    writer = csv.writer(expected)
    for row in selected:
        writer.writerow([("'" + cell['value']) if cell['value'].lstrip().startswith(('=', '+', '-', '@')) else cell['value'] for cell in row])
    assert sourcing_csv.export_rows(conn, tab, work_date=scope) == expected.getvalue()


def test_oversized_import_rolls_back_rows_columns_revision_and_operation(sheet, monkeypatch):
    conn, tab = sheet
    tab = sheets.owned(conn, tab['id'], {'role': 'admin', 'bidder_id': None})
    conn.execute('DELETE FROM native_rows WHERE tab_id=? AND id NOT IN (SELECT id FROM native_rows WHERE tab_id=? ORDER BY position,id LIMIT 1)', (tab['id'], tab['id']))
    conn.commit()
    before = sheets.snapshot(conn, tab)
    original_csv = sourcing_csv.export_rows(conn, tab)
    counts = tuple(conn.execute('SELECT (SELECT COUNT(*) FROM native_rows), (SELECT COUNT(*) FROM native_columns), (SELECT COUNT(*) FROM native_operations)').fetchone())
    monkeypatch.setattr(sheets, 'MAX_SNAPSHOT_CELLS', 10)
    with pytest.raises(sheets.SnapshotTooLarge):
        sourcing_csv.import_rows(conn, tab, 'too-large-import', before['revision'],
                                 text='Company,Role,Job link,Check,Extra\nNew,Engineer,https://example.test,,value',
                                 mode='append', has_header=True)
    assert tuple(conn.execute('SELECT (SELECT COUNT(*) FROM native_rows), (SELECT COUNT(*) FROM native_columns), (SELECT COUNT(*) FROM native_operations)').fetchone()) == counts
    assert str(conn.execute('SELECT revision FROM native_tabs WHERE id=?', (tab['id'],)).fetchone()[0]) == before['revision']
    assert sourcing_csv.export_rows(conn, tab) == original_csv
