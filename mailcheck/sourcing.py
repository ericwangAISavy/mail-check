"""Workbook ownership, cached search, and revision-checked literal cell saves."""
import json
import threading
import time
from contextlib import contextmanager
from . import db
from .google_sheets import GoogleError

SCHEMA='''
CREATE TABLE IF NOT EXISTS sourcing_books(id INTEGER PRIMARY KEY, bidder_id INTEGER NOT NULL UNIQUE REFERENCES bidders(id), spreadsheet_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sourcing_tabs(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES sourcing_books(id) ON DELETE CASCADE, sheet_id INTEGER NOT NULL, account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL, account_label TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, header_row INTEGER NOT NULL DEFAULT 1, company_col INTEGER NOT NULL DEFAULT 0, role_col INTEGER NOT NULL DEFAULT 1, link_col INTEGER NOT NULL DEFAULT 2, snapshot TEXT, refreshed_at REAL, UNIQUE(book_id,sheet_id), UNIQUE(book_id,account_id));
CREATE TABLE IF NOT EXISTS sourcing_operations(id TEXT PRIMARY KEY, tab_id INTEGER NOT NULL REFERENCES sourcing_tabs(id) ON DELETE CASCADE, payload TEXT NOT NULL, status TEXT NOT NULL, revision TEXT, created_at REAL NOT NULL, google_result TEXT);
'''
_lock=threading.RLock()
_tab_locks={}
@contextmanager
def worksheet_lock(tab_id):
    with _lock: lock=_tab_locks.setdefault(tab_id,threading.RLock())
    with lock: yield
def initialize(conn): conn.executescript(SCHEMA)
def column_name(index):
    value='';index+=1
    while index: index,remainder=divmod(index-1,26);value=chr(65+remainder)+value
    return value

def owned(conn,tab_id,identity):
    row=conn.execute('SELECT t.*,b.bidder_id,b.spreadsheet_id FROM sourcing_tabs t JOIN sourcing_books b ON b.id=t.book_id WHERE t.id=?',(tab_id,)).fetchone()
    if not row or (identity['role']!='admin' and row['bidder_id']!=identity['bidder_id']): raise PermissionError('Workbook not found.')
    return dict(row)

def refresh(conn,tab,google,*,force=True):
    with worksheet_lock(tab['id']):
        cached=conn.execute('SELECT snapshot,refreshed_at FROM sourcing_tabs WHERE id=?',(tab['id'],)).fetchone()
        if not force and cached and cached['snapshot'] and time.time()-(cached['refreshed_at'] or 0)<3:
            return {**json.loads(cached['snapshot']),'refreshed_at':cached['refreshed_at']}
        snapshot=google.snapshot(tab['spreadsheet_id'],tab['sheet_id'])
        stamp=time.time()
        conn.execute('UPDATE sourcing_tabs SET snapshot=?,refreshed_at=?,title=? WHERE id=?',(json.dumps(snapshot),stamp,snapshot['title'],tab['id']))
        conn.commit()
        return {**snapshot,'refreshed_at':stamp}


def save(conn,tab,google,operation,revision,changes):
    with worksheet_lock(tab['id']):
        payload=json.dumps({'revision':revision,'changes':changes},sort_keys=True)
        previous=conn.execute('SELECT * FROM sourcing_operations WHERE id=?',(operation,)).fetchone()
        if previous:
            if previous['tab_id']!=tab['id'] or previous['payload']!=payload: raise ValueError('Save ID was reused for different changes.')
            if previous['status']=='applied': return json.loads(previous['revision']) if previous['revision'] else refresh(conn,tab,google)
            raise GoogleError('This save has an uncertain outcome. Reload and compare your draft before saving again.')
        current=google.snapshot(tab['spreadsheet_id'],tab['sheet_id'])
        if current['revision']!=revision: raise FileExistsError('This sheet changed in Google or another session. Reload and compare your draft before saving.')
        patches=[]
        for change in changes:
            row,col,value=change['row'],change['col'],change['value']
            if row<tab['header_row'] or col<0 or row>=current['properties']['gridProperties']['rowCount'] or col>=current['properties']['gridProperties']['columnCount']: raise ValueError('Cell is outside the editable data area. Add rows or columns in Google Sheets first.')
            cells=current['rows'][row] if row<len(current['rows']) else []
            if col<len(cells) and cells[col]['formula']: raise ValueError('Formula cells are read-only.')
            title=current['title'].replace("'","''")
            patches.append({'range':f"'{title}'!{column_name(col)}{row+1}",'values':[[value]]})
        conn.execute('INSERT INTO sourcing_operations(id,tab_id,payload,status,revision,created_at) VALUES(?,?,?,?,?,?)',(operation,tab['id'],payload,'pending',None,time.time()));conn.commit()
        try: acknowledged=google.write(tab['spreadsheet_id'],patches)
        except GoogleError:
            conn.execute("UPDATE sourcing_operations SET status='uncertain' WHERE id=?",(operation,));conn.commit();raise
        conn.execute("UPDATE sourcing_operations SET status='applied',google_result=? WHERE id=?",(json.dumps(acknowledged),operation));conn.commit()
        result=refresh(conn,tab,google)
        conn.execute('UPDATE sourcing_operations SET revision=? WHERE id=?',(json.dumps(result),operation));conn.commit()
        return result


def append(conn,tab,google,operation,revision,rows):
    with worksheet_lock(tab['id']):
        payload=json.dumps({'revision':revision,'rows':rows},sort_keys=True)
        previous=conn.execute('SELECT * FROM sourcing_operations WHERE id=?',(operation,)).fetchone()
        if previous:
            if previous['tab_id']!=tab['id'] or previous['payload']!=payload: raise ValueError('Save ID was reused for different changes.')
            if previous['status']=='applied': return json.loads(previous['revision']) if previous['revision'] else refresh(conn,tab,google)
            raise GoogleError('This append has an uncertain outcome. Review the sheet before appending again.')
        if conn.execute("SELECT 1 FROM sourcing_operations WHERE tab_id=? AND status IN ('pending','uncertain')",(tab['id'],)).fetchone(): raise GoogleError('Review the previous uncertain save before appending more jobs.')
        current=google.snapshot(tab['spreadsheet_id'],tab['sheet_id'])
        if current['revision']!=revision: raise FileExistsError('This sheet changed. Reload before appending jobs.')
        if sum(len(r) for r in rows)>10000 or any(len(r)>current['properties']['gridProperties']['columnCount'] for r in rows): raise ValueError('Paste up to 10,000 cells within the existing sheet columns.')
        conn.execute('INSERT INTO sourcing_operations(id,tab_id,payload,status,revision,created_at) VALUES(?,?,?,?,?,?)',(operation,tab['id'],payload,'pending',None,time.time()));conn.commit()
        try: acknowledged=google.append(tab['spreadsheet_id'],current['title'],rows)
        except GoogleError:
            conn.execute("UPDATE sourcing_operations SET status='uncertain' WHERE id=?",(operation,));conn.commit();raise
        conn.execute("UPDATE sourcing_operations SET status='applied',google_result=? WHERE id=?",(json.dumps(acknowledged),operation));conn.commit()
        result=refresh(conn,tab,google)
        conn.execute('UPDATE sourcing_operations SET revision=? WHERE id=?',(json.dumps(result),operation));conn.commit()
        return result
