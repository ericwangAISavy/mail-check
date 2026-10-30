"""Owner-only local archive APIs. Restore stays an offline CLI operation."""
import os
from urllib.parse import urlencode
from starlette.background import BackgroundTask
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool
from ..backups import BackupError


class BackupSettings(BaseModel):
    enabled: StrictBool
    retain: int = Field(ge=1,le=30,strict=True)


def install(app,manager,owner):
    @app.get('/api/admin/backups')
    def status(request:Request):
        owner(request)
        try:return manager.status()
        except BackupError as exc:raise HTTPException(400,str(exc)) from exc

    @app.post('/api/admin/backups/settings')
    def settings(body:BackupSettings,request:Request):
        owner(request)
        try:return manager.configure(body.enabled,body.retain)
        except BackupError as exc:raise HTTPException(400,str(exc)) from exc

    @app.post('/api/admin/backups/create')
    def create(request:Request):
        owner(request)
        try:return manager.create()
        except (BackupError,OSError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from exc

    def stream_archive(path,name):
        try:stream=path.open('rb')
        except OSError as exc:raise HTTPException(404,'Backup is unavailable.') from exc
        def chunks():
            try:
                for chunk in iter(lambda:stream.read(1024*1024),b''):yield chunk
            finally:stream.close()
        return StreamingResponse(chunks(),media_type='application/zip',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','Content-Disposition':f'attachment; filename="{name}"','Content-Length':str(os.fstat(stream.fileno()).st_size)},background=BackgroundTask(stream.close))

    @app.post('/api/admin/backups/download-ticket/{name}')
    def download_ticket(name:str,request:Request):
        identity=owner(request)
        try:token=manager.issue_ticket(name,request.cookies.get('offerpath_session',''),identity['workspace_id'])
        except BackupError as exc:raise HTTPException(400,str(exc)) from exc
        return {'url':f'/api/admin/backups/file/{name}?'+urlencode({'ticket':token,'workspace':identity['workspace_id']})}

    @app.get('/api/admin/backups/file/{name}')
    def native_download(name:str,request:Request,ticket:str='',workspace:str=''):
        identity=owner(request)
        try:path=manager.consume_ticket(name,ticket,request.cookies.get('offerpath_session',''),identity['workspace_id'])
        except BackupError as exc:raise HTTPException(403,str(exc)) from exc
        return stream_archive(path,name)

    @app.get('/api/admin/backups/download/{name}')
    def download(name:str,request:Request):
        owner(request)
        try:path=manager.download_path(name)
        except BackupError as exc:raise HTTPException(404,str(exc)) from exc
        return stream_archive(path,name)
