"""Sourcing endpoints. Every data lookup checks workbook ownership before access."""
import json
import uuid
from contextlib import contextmanager
from typing import Annotated
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field
from .. import db, sourcing
from ..google_oauth import GoogleConnection
from ..google_sheets import SheetsClient, GoogleError, spreadsheet_id

class Setup(BaseModel):
    client_id: str=Field(min_length=1,max_length=512)
    client_secret: str=Field(min_length=1,max_length=512)
    redirect_uri: str=Field(max_length=1024)
class Book(BaseModel):
    bidder_id: int
    url: str=Field(max_length=1024)
class Tab(BaseModel):
    sheet_id: int
    account_id: int
    header_row: int=Field(default=1,ge=1,le=100)
    company_col: int=Field(default=0,ge=0,le=100)
    role_col: int=Field(default=1,ge=0,le=100)
    link_col: int=Field(default=2,ge=0,le=100)
class Change(BaseModel):
    row: int=Field(ge=0,le=1000000)
    col: int=Field(ge=0,le=100)
    value: str=Field(max_length=50000)
class Append(BaseModel):
    operation: uuid.UUID
    revision: str=Field(min_length=1,max_length=128)
    rows: list[list[Annotated[str,Field(max_length=50000)]]]=Field(min_length=1,max_length=1000)

class Save(BaseModel):
    operation: uuid.UUID
    revision: str=Field(min_length=1,max_length=128)
    changes: list[Change]=Field(min_length=1,max_length=10000)

def install(app,frontend_page,secure_cookies):
    router=APIRouter()
    app.state.google_connection=GoogleConnection()
    app.state.sheets_client=None
    def google(): return app.state.sheets_client or SheetsClient(app.state.google_connection.token)
    def identity(req): return {'role':req.state.role,'bidder_id':req.state.bidder_id}
    def admin(req):
        if req.state.role!='admin': raise HTTPException(403,'Admin access required.')
    @contextmanager
    def connection():
        with db.session() as conn:
            yield conn
    @app.exception_handler(GoogleError)
    async def google_error(req,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'error':str(exc)},status_code=502)
    @router.get('/sourcing')
    def page(): return frontend_page()
    @router.get('/api/sourcing/google')
    def status(req:Request): admin(req);return app.state.google_connection.status()
    @router.post('/api/sourcing/google/setup')
    def setup(body:Setup,req:Request):
        admin(req)
        try: app.state.google_connection.setup(**body.model_dump())
        except ValueError as exc: raise HTTPException(400,str(exc))
        return {'ok':True}
    @router.post('/api/sourcing/google/connect')
    def begin(req:Request):
        from fastapi.responses import JSONResponse
        admin(req)
        try: state=app.state.google_connection.begin()
        except ValueError as exc: raise HTTPException(400,str(exc))
        response=JSONResponse({'url':state['url']})
        response.set_cookie('google_oauth',state['cookie'],max_age=600,httponly=True,samesite='lax',secure=secure_cookies,path='/api/google/callback')
        return response
    @router.post('/api/sourcing/google/disconnect')
    def disconnect(req:Request): admin(req);app.state.google_connection.disconnect();return {'ok':True}
    @router.get('/api/google/callback')
    def callback(req:Request,state:str='',code:str=''):
        try: app.state.google_connection.complete(state,code,req.cookies.get('google_oauth',''))
        except ValueError as exc: raise HTTPException(400,str(exc))
        response=RedirectResponse('/sourcing?connected=1',303);response.delete_cookie('google_oauth',path='/api/google/callback');return response
    @router.get('/api/sourcing')
    def index(req:Request):
        with connection() as conn:
            is_admin=req.state.role=='admin'
            books=[dict(r) for r in conn.execute('SELECT b.*,p.name FROM sourcing_books b JOIN bidders p ON p.id=b.bidder_id WHERE (? OR b.bidder_id=?) ORDER BY p.name',(is_admin,req.state.bidder_id))]
            for book in books:
                book['tabs']=[dict(r) for r in conn.execute('SELECT id,sheet_id,account_id,account_label,title,header_row,company_col,role_col,link_col,refreshed_at FROM sourcing_tabs WHERE book_id=? ORDER BY id',(book['id'],))]
            result={'books':books}
            if is_admin:
                result['bidders']=[dict(r) for r in conn.execute('SELECT id,name,login_enabled FROM bidders ORDER BY name')]
                result['accounts']=[dict(r) for r in conn.execute('SELECT id,email,label FROM accounts WHERE enabled=1')]
                result['assignments']=[dict(r) for r in conn.execute('SELECT bidder_id,account_id FROM bidder_assignments WHERE end_date IS NULL OR end_date>=date(\'now\')')]
            return result
    @router.post('/api/sourcing/books')
    def add_book(body:Book,req:Request):
        admin(req)
        try: book_id=spreadsheet_id(body.url)
        except ValueError as exc: raise HTTPException(400,str(exc))
        metadata=google().metadata(book_id)
        google().verify_edit(book_id)
        with connection() as conn:
            if not conn.execute('SELECT 1 FROM bidders WHERE id=?',(body.bidder_id,)).fetchone(): raise HTTPException(404,'Bidder not found.')
            try: conn.execute('INSERT INTO sourcing_books(bidder_id,spreadsheet_id,title) VALUES(?,?,?)',(body.bidder_id,book_id,metadata.get('properties',{}).get('title',book_id)));conn.commit()
            except Exception as exc:
                import sqlite3
                if isinstance(exc,sqlite3.IntegrityError): raise HTTPException(409,'This bidder or spreadsheet is already connected.')
                raise
        return {'ok':True}
    @router.post('/api/sourcing/books/{book_id}/remove')
    def unlink(book_id:int,req:Request):
        admin(req)
        with connection() as conn: conn.execute('DELETE FROM sourcing_books WHERE id=?',(book_id,));conn.commit()
        return {'ok':True}
    @router.get('/api/sourcing/books/{book_id}/metadata')
    def metadata(book_id:int,req:Request):
        admin(req)
        with connection() as conn:
            book=conn.execute('SELECT * FROM sourcing_books WHERE id=?',(book_id,)).fetchone()
            if not book: raise HTTPException(404,'Workbook not found.')
            return google().metadata(book['spreadsheet_id'])
    @router.get('/api/sourcing/books/{book_id}/preview/{sheet_id}')
    def preview(book_id:int,sheet_id:int,req:Request):
        import re
        admin(req)
        with connection() as conn:
            book=conn.execute('SELECT * FROM sourcing_books WHERE id=?',(book_id,)).fetchone()
            if not book: raise HTTPException(404,'Workbook not found.')
            snapshot=google().snapshot(book['spreadsheet_id'],sheet_id)
            for number,row in enumerate(snapshot['rows'][:20]):
                columns={re.sub(r'[^a-z]','',cell.get('display','').lower()):i for i,cell in enumerate(row)}
                aliases={'company_col':('company','companyname','employer'),'role_col':('role','jobtitle','position','jobrole'),'link_col':('joblink','joburl','url','link','applicationlink')}
                found={field:next((columns[name] for name in names if name in columns),None) for field,names in aliases.items()}
                if all(value is not None for value in found.values()): return {'suggested':{'header_row':number+1,**found}}
            return {'suggested':None}
    @router.post('/api/sourcing/books/{book_id}/tabs')
    def map_tab(book_id:int,body:Tab,req:Request):
        admin(req)
        with connection() as conn:
            book=conn.execute('SELECT * FROM sourcing_books WHERE id=?',(book_id,)).fetchone()
            if not book: raise HTTPException(404,'Workbook not found.')
            if not conn.execute('SELECT 1 FROM bidder_assignments WHERE bidder_id=? AND account_id=?',(book['bidder_id'],body.account_id)).fetchone(): raise HTTPException(400,'Assign this profile to the bidder on Bidder payments first.')
            if len({body.company_col,body.role_col,body.link_col})!=3: raise HTTPException(400,'Choose three different search columns.')
            snapshot=google().snapshot(book['spreadsheet_id'],body.sheet_id)
            label=conn.execute('SELECT email FROM accounts WHERE id=?',(body.account_id,)).fetchone()[0]
            if body.header_row>=snapshot['properties']['gridProperties']['rowCount'] or max(body.company_col,body.role_col,body.link_col)>=snapshot['properties']['gridProperties']['columnCount']: raise HTTPException(400,'The header or search columns are outside this tab.')
            try: conn.execute('INSERT INTO sourcing_tabs(book_id,sheet_id,account_id,account_label,title,header_row,company_col,role_col,link_col,snapshot,refreshed_at) VALUES(?,?,?,?,?,?,?,?,?,?,strftime(\'%s\',\'now\'))',(book_id,body.sheet_id,body.account_id,label,snapshot['title'],body.header_row,body.company_col,body.role_col,body.link_col,json.dumps(snapshot)));conn.commit()
            except Exception as exc:
                import sqlite3
                if isinstance(exc,sqlite3.IntegrityError): raise HTTPException(409,'This tab or profile is already mapped.')
                raise
        return {'ok':True}
    @router.post('/api/sourcing/tabs/{tab_id}/remove')
    def remove(tab_id:int,req:Request):
        admin(req)
        with connection() as conn: conn.execute('DELETE FROM sourcing_tabs WHERE id=?',(tab_id,));conn.commit()
        return {'ok':True}
    @router.get('/api/sourcing/tabs/{tab_id}')
    def snapshot(tab_id:int,req:Request):
        with connection() as conn:
            try: tab=sourcing.owned(conn,tab_id,identity(req))
            except PermissionError: raise HTTPException(404,'Workbook not found.')
            try: return sourcing.refresh(conn,tab,google(),force=False)
            except GoogleError as exc:
                if tab['snapshot']: return {**json.loads(tab['snapshot']),'refreshed_at':tab['refreshed_at'],'stale':True,'error':str(exc)}
                raise
    @router.post('/api/sourcing/tabs/{tab_id}/save')
    def save(tab_id:int,body:Save,req:Request):
        with connection() as conn:
            try:
                tab=sourcing.owned(conn,tab_id,identity(req))
                return sourcing.save(conn,tab,google(),str(body.operation),body.revision,[c.model_dump() for c in body.changes])
            except PermissionError: raise HTTPException(404,'Workbook not found.')
            except FileExistsError as exc: raise HTTPException(409,str(exc))
            except GoogleError: raise
            except ValueError as exc: raise HTTPException(400,str(exc))
    @router.post('/api/sourcing/tabs/{tab_id}/append')
    def append(tab_id:int,body:Append,req:Request):
        with connection() as conn:
            try:
                tab=sourcing.owned(conn,tab_id,identity(req))
                return sourcing.append(conn,tab,google(),str(body.operation),body.revision,body.rows)
            except PermissionError: raise HTTPException(404,'Workbook not found.')
            except FileExistsError as exc: raise HTTPException(409,str(exc))
            except GoogleError: raise
            except ValueError as exc: raise HTTPException(400,str(exc))
    @router.post('/api/sourcing/tabs/{tab_id}/review')
    def review(tab_id:int,req:Request):
        with connection() as conn:
            try: tab=sourcing.owned(conn,tab_id,identity(req))
            except PermissionError: raise HTTPException(404,'Workbook not found.')
            result=sourcing.refresh(conn,tab,google())
            conn.execute("UPDATE sourcing_operations SET status='reviewed' WHERE tab_id=? AND status IN ('pending','uncertain')",(tab_id,));conn.commit()
            return result
    @router.post('/api/sourcing/refresh')
    def refresh_all(req:Request):
        failures=[];refreshed=0
        with connection() as conn:
            tabs=conn.execute('SELECT t.id FROM sourcing_tabs t JOIN sourcing_books b ON b.id=t.book_id WHERE (? OR b.bidder_id=?)',(req.state.role=='admin',req.state.bidder_id)).fetchall()
            for row in tabs:
                tab=sourcing.owned(conn,row['id'],identity(req))
                try: sourcing.refresh(conn,tab,google());refreshed+=1
                except GoogleError as exc: failures.append({'tab_id':tab['id'],'error':str(exc)})
        return {'refreshed':refreshed,'failures':failures}
    @router.get('/api/sourcing/search')
    def search(req:Request,q:str='',account:int|None=None):
        with connection() as conn:
            rows=conn.execute('SELECT t.*,b.bidder_id,b.spreadsheet_id,p.name FROM sourcing_tabs t JOIN sourcing_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id WHERE (? OR b.bidder_id=?) AND (? IS NULL OR t.account_id=?)',(req.state.role=='admin',req.state.bidder_id,account,account)).fetchall()
            results=[]
            for tab in rows:
                snapshot=json.loads(tab['snapshot'] or '{}')
                for index,row in enumerate(snapshot.get('rows',[])):
                    if index<tab['header_row']: continue
                    values=[row[c].get('display','') if c<len(row) else '' for c in (tab['company_col'],tab['role_col'],tab['link_col'])]
                    if tab['link_col']<len(row): values[2]=row[tab['link_col']].get('link') or values[2]
                    if q.strip() and all(word in ' '.join([*values,tab['name'],tab['title'],tab['account_label']]).lower() for word in q.lower().split()):
                        results.append({'tab_id':tab['id'],'bidder':tab['name'],'profile':tab['title'],'row':index,'company':values[0],'role':values[1],'link':values[2],'refreshed_at':tab['refreshed_at']})
            return {'results':results[:500],'cached':True,'tabs':len(rows),'incomplete':any(not r['snapshot'] for r in rows)}
    app.include_router(router)
