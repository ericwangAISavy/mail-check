"""Admin-only, revision-checked interview opportunity endpoints."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import db, interview_pipeline as pipeline


class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: UUID


class Versioned(Operation):
    revision: int = Field(ge=1)


class Create(Operation):
    account_id: int = Field(ge=1)
    company: str = Field(min_length=1, max_length=253)
    role: str = Field(default='', max_length=300)
    job_url: str = Field(default='', max_length=4000)
    application_ref: str = Field(default='', max_length=500)
    timezone: str = Field(default='America/Chicago', max_length=100)


class Edit(Versioned):
    changes: dict


class Review(Operation):
    action: Literal['accept','dismiss','link']
    key: str = Field(min_length=1,max_length=300)
    company: str | None = Field(default=None,max_length=253)
    role: str | None = Field(default=None,max_length=300)
    target_id: str | None = Field(default=None,max_length=100)
    revision: int | None = Field(default=None,ge=1)


class Evidence(Versioned):
    action: Literal['link','unlink']
    kind: Literal['event','message']
    source_id: int = Field(ge=1)


class Attendance(Versioned):
    event_id: int = Field(ge=1)
    attendance: Literal['Unconfirmed','Attended','Did not attend']
    start_at: str = Field(min_length=1,max_length=100)


class Task(Versioned):
    title: str = Field(min_length=1,max_length=500)
    due_at: str | None = Field(default=None,max_length=100)
    kind: str = Field(default='task',max_length=80)
    responsibility: str = Field(default='you',max_length=80)


class TaskEdit(Versioned):
    state: Literal['open','done','dismissed','snoozed']
    snoozed_until: str | None = Field(default=None,max_length=100)


class Contact(Versioned):
    at: str = Field(min_length=1,max_length=100)
    expects_reply: bool
    note: str = Field(default='',max_length=8000)


class Note(Versioned):
    text: str = Field(min_length=1,max_length=8000)


class Merge(Versioned):
    source_id: str = Field(min_length=1,max_length=100)
    source_revision: int = Field(ge=1)


class Split(Versioned):
    company: str = Field(min_length=1,max_length=253)
    role: str = Field(default='',max_length=300)
    event_ids: list[int] = Field(default_factory=list,max_length=1000)
    message_ids: list[int] = Field(default_factory=list,max_length=1000)
    task_ids: list[str] = Field(default_factory=list,max_length=1000)


def install(app):
    router = APIRouter(prefix='/api/pipeline')

    def admin(request):
        if getattr(request.state,'role',None) != 'admin' or getattr(request.state,'viewer_read_only',False):
            raise HTTPException(403,'Admin access required.')

    def read(request,function):
        admin(request)
        try:
            with db.session() as conn:
                return function(conn)
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    def body(value):
        return value.model_dump(mode='json',exclude_none=True)

    @router.get('')
    def listing(request:Request,view:Literal['active','attention','upcoming','closed','archived']='active',
                q:str=Query(default='',max_length=200),account_id:int|None=Query(default=None,ge=1)):
        return read(request,lambda conn:pipeline.list_data(conn,view=view,q=q,account_id=account_id))

    @router.post('')
    def create(request:Request,value:Create):
        return read(request,lambda conn:pipeline.create(conn,body(value)))

    @router.get('/review')
    def review(request:Request,q:str=Query(default='',max_length=200),account_id:int|None=Query(default=None,ge=1),
               limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0,le=1000000)):
        return read(request,lambda conn:pipeline.review(conn,q=q,account_id=account_id,limit=limit,offset=offset))

    @router.post('/review')
    def decide(request:Request,value:Review):
        return read(request,lambda conn:pipeline.review_action(conn,body(value)))

    @router.post('/activate')
    def activate(request:Request,value:Operation):
        return read(request,lambda conn:pipeline.activate(conn,body(value)))

    @router.get('/{identity}')
    def detail(identity:str,request:Request):
        return read(request,lambda conn:pipeline.detail(conn,identity))

    @router.post('/{identity}')
    def edit(identity:str,request:Request,value:Edit):
        return read(request,lambda conn:pipeline.update(conn,identity,body(value)))

    @router.post('/{identity}/evidence')
    def evidence(identity:str,request:Request,value:Evidence):
        return read(request,lambda conn:pipeline.evidence(conn,identity,body(value)))

    @router.post('/{identity}/attendance')
    def attendance(identity:str,request:Request,value:Attendance):
        return read(request,lambda conn:pipeline.attendance(conn,identity,body(value)))

    @router.post('/{identity}/tasks')
    def task(identity:str,request:Request,value:Task):
        return read(request,lambda conn:pipeline.add_task(conn,identity,body(value)))

    @router.post('/{identity}/tasks/{task_id}')
    def edit_task(identity:str,task_id:str,request:Request,value:TaskEdit):
        return read(request,lambda conn:pipeline.update_task(conn,identity,task_id,body(value)))

    @router.post('/{identity}/contact')
    def contact(identity:str,request:Request,value:Contact):
        return read(request,lambda conn:pipeline.add_contact(conn,identity,body(value)))

    @router.post('/{identity}/notes')
    def note(identity:str,request:Request,value:Note):
        return read(request,lambda conn:pipeline.add_note(conn,identity,body(value)))

    @router.post('/{identity}/merge')
    def merge(identity:str,request:Request,value:Merge):
        return read(request,lambda conn:pipeline.merge(conn,identity,body(value)))

    @router.post('/{identity}/split')
    def split(identity:str,request:Request,value:Split):
        return read(request,lambda conn:pipeline.split(conn,identity,body(value)))

    app.include_router(router)
