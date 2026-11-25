"""Admin-only company feedback, independent of calendar loading."""
from contextlib import closing,contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Literal

from fastapi import HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field

from .. import config,interview_feedback as feedback


class FeedbackBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:int=Field(gt=0)
    company:str=Field(min_length=1,max_length=200)
    tags:list[Literal['in-person','linkedin','fuck','normal']]=Field(max_length=4)


def event_company(path,event_id,expected):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)) as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('''SELECT e.* FROM interview_events e WHERE id=?
            AND NOT EXISTS(SELECT 1 FROM interview_event_removals r WHERE r.event_id=e.id)''',(event_id,)).fetchone()
        if row is None:raise HTTPException(404,'Interview not found.')
        company=row['company']
        if feedback.company_key(company)!=feedback.company_key(expected):
            raise HTTPException(409,'The interview company changed. Reopen event details before sharing feedback.')
        manual=json.loads(row['manual_fields'])
        if 'company' not in manual and conn.execute('SELECT 1 FROM interview_sources WHERE event_id=? AND message_pk IS NULL AND source_subject=? LIMIT 1',(event_id,company)).fetchone():
            raise HTTPException(422,'Set the actual company in interview details before sharing feedback.')
        return company


def install(app,*,store=None,original_db=None,gateway_managed=False):
    def actor(request):
        if gateway_managed:raise HTTPException(403,'Use the permission-checked gateway for shared feedback.')
        identity=request.state.identity if store else {'role':request.state.role,'workspace_id':'local','user_id':'local-admin'}
        if not identity or identity['role']!='admin':raise HTTPException(403,'Admin access required.')
        return identity,identity['workspace_id'],str(identity['user_id'])

    @contextmanager
    def storage(write=False):
        if store:
            with store.connect() as conn:
                yield conn
            return
        path=Path(config.db_path()).with_name('interview-feedback.db')
        if not write and not path.is_file():
            yield None
            return
        if write:
            from ..maintenance import connect_database
            conn=connect_database(path,timeout=1)
        else:
            conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
        conn.row_factory=sqlite3.Row
        try:
            if write:conn.executescript(feedback.SCHEMA)
            yield conn
            if write:conn.commit()
        except BaseException:
            if write:conn.rollback()
            raise
        finally:conn.close()

    def recheck(request,workspace):
        if store:
            try:store.validate_dispatch(request.cookies.get('offerpath_session'),workspace,read_only=True)
            except PermissionError:raise HTTPException(401,'Session changed. Sign in again.') from None

    @app.get('/api/interview-feedback')
    def read(request:Request,companies:str=Query('[]',max_length=10000)):
        identity,workspace,author=actor(request)
        try:
            names=json.loads(companies)
            if not isinstance(names,list) or len(names)>40:raise ValueError('Request up to 40 companies at a time.')
            if any(not isinstance(name,str) or not name.strip() or len(name)>200 for name in names):
                raise ValueError('Invalid company name.')
        except (ValueError,TypeError):raise HTTPException(422,'Choose up to 40 actual company names of 1–200 characters.') from None
        eligible=[]
        result={}
        for name in names:
            try:feedback.company_key(name)
            except ValueError:result[name]={'tags':[],'mine':[]}
            else:eligible.append(name)
        try:
            with storage() as conn:result.update(feedback.summary(conn,eligible,workspace,author))
            recheck(request,workspace)
            return {'companies':result,'options':feedback.OPTIONS}
        except (sqlite3.Error,OSError,ValueError):raise HTTPException(503,'Interview feedback is temporarily unavailable. Try again.') from None

    @app.post('/api/interview-feedback')
    def write(request:Request,body:FeedbackBody):
        identity,workspace,author=actor(request)
        try:
            if store:
                record=store.workspace(workspace)
                from ..workspaces import WorkspaceContext
                context=WorkspaceContext.from_record(record,(config.config_path(),original_db),store.root)
                path=context.root/'data'/'mailcheck.db' if context.root else original_db
            else:path=config.db_path()
            company=event_company(path,body.event_id,body.company)
            with storage(write=True) as conn:
                conn.execute('BEGIN IMMEDIATE')
                if store:
                    try:store.require_session(conn,request.cookies.get('offerpath_session'),workspace=workspace)
                    except PermissionError:raise HTTPException(401,'Session changed. Sign in again.') from None
                feedback.save(conn,workspace,author,company,body.tags)
            return {'ok':True}
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        except (sqlite3.Error,OSError):raise HTTPException(503,'Interview feedback is temporarily unavailable. Try again.') from None
