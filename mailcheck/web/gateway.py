"""Network-facing multi-workspace gateway; business APIs execute in isolated workers."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config
from ..control_store import ControlStore, RevokedSession
from ..workspace_workers import InstanceLock, WorkerPool
from .auth import AuthStore, AuthFileError

COOKIE='offerpath_session'
HERE=Path(__file__).parent


class Login(BaseModel):
    username: str = Field(default='owner',max_length=64)
    password: str = Field(min_length=1,max_length=256)
    role: str = Field(default='admin',max_length=16)


class NewAdmin(BaseModel):
    username: str = Field(min_length=3,max_length=64)
    workspace_name: str = Field(min_length=1,max_length=100)
    password: str = Field(min_length=12,max_length=256)


class AdminUpdate(BaseModel):
    enabled: bool | None = None
    password: str | None = Field(default=None,min_length=12,max_length=256)


class Password(BaseModel):
    password: str = Field(min_length=12,max_length=256)
    role: str = 'admin'


class Switch(BaseModel):
    workspace_id: str = Field(min_length=1,max_length=32)


def create_gateway(*,allowed_hosts=None,secure_cookies=False,max_workspaces=4,store=None,pool=None,gateway_url='http://127.0.0.1:52400',start_workers=True):
    if not 1<=max_workspaces<=64:raise ValueError('Choose 1–64 maximum workspaces.')
    original_config=config.config_path(); original_db=config.db_path(); original_auth=config.config_dir()/'web-auth.json'
    store=store or ControlStore(config.config_dir()/'offerpath-control',AuthStore(lambda:original_auth),max_workspaces)
    pool=pool or WorkerPool(store,gateway_url,(original_config,original_db,original_auth))
    model_slots=asyncio.Semaphore(1)
    leases={}

    async def recover_leases():
        while True:
            await asyncio.sleep(5)
            for token, lease in list(leases.items()):
                if not await asyncio.to_thread(pool.authenticate_worker,lease[2]):
                    if leases.pop(token,None):lease[1].cancel();model_slots.release()

    @asynccontextmanager
    async def lifespan(app):
        with InstanceLock(store.root/'gateway.lock'):
            # Start independently from browser sessions, so scheduled checks survive tab closure.
            monitor=asyncio.create_task(pool.monitor()) if start_workers else None
            recovery=asyncio.create_task(recover_leases())
            try:yield
            finally:
                if monitor:
                    monitor.cancel()
                    with suppress(asyncio.CancelledError):await monitor
                recovery.cancel()
                with suppress(asyncio.CancelledError):await recovery
                await asyncio.to_thread(pool.close)

    app=FastAPI(title='OfferPath',docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.control_store=store;app.state.worker_pool=pool
    hosts={'127.0.0.1','localhost','::1','testserver',*(h.lower() for h in allowed_hosts or [])}
    internal_host=urlparse(gateway_url).hostname
    if internal_host:hosts.add(internal_host.lower())
    assets=HERE/'frontend_dist'/'assets'
    if assets.is_dir():app.mount('/assets',StaticFiles(directory=assets),name='assets')
    app.mount('/static',StaticFiles(directory=HERE/'static'),name='static')

    def page():
        return FileResponse(HERE/'frontend_dist'/'index.html',headers={'Cache-Control':'no-store'})

    def cookie(response,token):
        response.set_cookie(COOKIE,token,max_age=43200,httponly=True,secure=secure_cookies,samesite='strict',path='/')
        response.delete_cookie('mailcheck_session',path='/')
        return response

    def owner(request):
        identity=request.state.identity
        if not identity or not identity['is_owner']:raise HTTPException(403,'Owner access required.')
        return identity

    @app.middleware('http')
    async def boundary(request,call_next):
        host=urlparse('//'+request.headers.get('host','')).hostname or ''
        if host.lower() not in hosts:return JSONResponse({'error':'Unrecognised Host header.'},403)
        path=request.url.path
        if path.startswith('/_internal/'):
            wid=await asyncio.to_thread(pool.authenticate_worker,request.headers.get('x-offerpath-worker',''))
            if not wid:return JSONResponse({'error':'Internal access denied.'},403)
            request.state.worker=wid
            return await call_next(request)
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if (origin and origin!=f'{request.url.scheme}://{request.headers.get("host","")}') or request.headers.get('sec-fetch-site')=='cross-site':return JSONResponse({'error':'Cross-origin requests are not allowed.'},403)
        try:identity=await asyncio.to_thread(store.identity,request.cookies.get(COOKIE))
        except (AuthFileError,ValueError,OSError):return JSONResponse({'error':'Owner authentication is unavailable. Restore the original sign-in file.'},503)
        request.state.identity=identity
        public=path in ('/login','/api/auth/login','/api/auth/logout','/api/auth/session') or path.startswith(('/assets/','/static/'))
        if not public:
            if not identity:
                return JSONResponse({'error':'Sign in to continue.'},401) if path.startswith('/api/') else RedirectResponse('/login',303)
            expected=request.headers.get('x-offerpath-workspace')
            if path.startswith('/api/') and expected!=identity['workspace_id']:
                return JSONResponse({'error':'Workspace changed. Reload before continuing.','workspace_changed':True},409)
            if identity['must_change_password'] and path not in ('/api/auth/password','/login'):
                return JSONResponse({'error':'Change your temporary password before opening the workspace.'},403) if path.startswith('/api/') else page()
        try:response=await call_next(request)
        except RevokedSession as exc:
            response=JSONResponse({"error":str(exc)},401)
        except (ValueError,PermissionError) as exc:
            response=JSONResponse({'error':str(exc)},403 if isinstance(exc,PermissionError) else 400)
        except AuthFileError:
            response=JSONResponse({'error':'The original owner sign-in file is unavailable.'},503)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'DENY'})
        return response

    @app.get('/_internal/ping')
    def ping():return {'ok':True}

    @app.post('/_internal/model/acquire')
    async def acquire(request:Request):
        # asyncio.Semaphore queues pending tasks FIFO. Lease expiry recovers dead workers.
        try:await asyncio.wait_for(model_slots.acquire(),timeout=600)
        except asyncio.TimeoutError:raise HTTPException(503,'The shared model queue is busy.')
        if not await asyncio.to_thread(pool.authenticate_worker,request.headers.get('x-offerpath-worker','')):
            model_slots.release();raise HTTPException(403,'Workspace worker is no longer active.')
        import secrets
        token=secrets.token_urlsafe(32)
        loop=asyncio.get_running_loop()
        def release():
            if leases.pop(token,None):model_slots.release()
        leases[token]=(request.state.worker,loop.call_later(900,release),request.headers['x-offerpath-worker'])
        return {'lease':token}

    @app.post('/_internal/model/release')
    async def release(request:Request):
        body=await request.json();token=body.get('lease','')
        lease=leases.get(token)
        if lease and lease[0]==request.state.worker:
            leases.pop(token);lease[1].cancel();model_slots.release()
        return {'ok':True}

    @app.get('/api/auth/session')
    def session(request:Request):
        return request.state.identity or {'role':None,'managed':True}

    @app.post('/api/auth/login')
    async def login(body:Login,request:Request):
        if body.role!='admin':raise HTTPException(401,'Bidder sign-in has been removed. Sign in with an owner or admin account.')
        try:token=await asyncio.to_thread(store.login,body.username,body.password,request.client.host if request.client else 'unknown')
        except ValueError:raise HTTPException(429,'Too many sign-in attempts. Try again in a minute.',headers={'Retry-After':'60'})
        if not token:raise HTTPException(401,'Incorrect username or password.')
        return cookie(JSONResponse(store.identity(token)),token)

    @app.post('/api/auth/logout')
    def logout(request:Request):
        store.logout(request.cookies.get(COOKIE))
        response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');response.delete_cookie('mailcheck_session',path='/')
        return response

    @app.post('/api/auth/password')
    def change_password(body:Password,request:Request):
        if body.role!='admin':raise HTTPException(400,'Only admin passwords are supported.')
        token=store.change_password(request.cookies.get(COOKIE),body.password,expected_workspace=request.headers.get('x-offerpath-workspace'))
        return cookie(JSONResponse({'ok':True,'message':'Password updated. Other sessions have been signed out.','session':store.identity(token)}),token)

    @app.api_route('/api/auth/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    def removed_auth(path:str):raise HTTPException(410,'Bidder sign-in and credential management have been removed.')

    @app.get('/api/admin/users')
    def admins(request:Request):
        owner(request)
        status=pool.status()
        starts=getattr(pool,"start_times",lambda:{})()
        return {'admins':[{**u,'worker_started_at':starts.get(u['workspace_id']),'health':status.get(u['workspace_id'],'starting or unavailable') if u['enabled'] else 'suspended'} for u in store.list_admins()], 'max_workspaces':store.max_workspaces}

    @app.post('/api/admin/users')
    async def create_admin(body:NewAdmin,request:Request):
        identity=owner(request)
        wid=await asyncio.to_thread(store.create_admin,request.cookies.get(COOKIE),body.username,body.workspace_name,body.password,expected_workspace=request.headers.get('x-offerpath-workspace'))
        # The supervisor starts the worker; provisioning can succeed independently of mailbox setup.
        return {'ok':True,'workspace_id':wid}

    @app.post('/api/admin/users/{user_id}')
    async def update_admin(user_id:int,body:AdminUpdate,request:Request):
        identity=owner(request)
        if body.enabled is None and body.password is None:raise HTTPException(400,'Choose a password reset or access change.')
        wid=await asyncio.to_thread(store.update_admin,request.cookies.get(COOKIE),user_id,enabled=body.enabled,password=body.password,expected_workspace=request.headers.get('x-offerpath-workspace'))
        if body.enabled is False:await asyncio.to_thread(pool.stop,wid)
        elif body.enabled is True:pool.enable(wid)
        return {'ok':True}

    @app.post('/api/admin/switch')
    def switch(body:Switch,request:Request):
        identity=owner(request)
        token=store.switch(request.cookies.get(COOKIE),body.workspace_id,expected_workspace=request.headers.get('x-offerpath-workspace'))
        return cookie(JSONResponse(store.identity(token)),token)

    @app.get('/api/admin/audit')
    def audit(request:Request):
        owner(request)
        with store.connect() as conn:return {'events':[dict(r) for r in conn.execute('SELECT id,at,actor,action,target FROM audit ORDER BY id DESC LIMIT 100')]}

    @app.api_route('/api/admin/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    def missing_admin(path:str,request:Request):owner(request);raise HTTPException(404,'Not found.')

    @app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
    async def proxy(path:str,request:Request):
        if not path.startswith('api/'):
            return page()
        identity=request.state.identity
        try:worker=await asyncio.to_thread(pool.ensure,store.workspace(identity['workspace_id']))
        except (RuntimeError,OSError,ValueError):raise HTTPException(503,'This workspace worker is unavailable. Contact the owner or retry later.')
        body=await request.body()
        if len(body)>4_000_000:raise HTTPException(413,'Request is too large.')
        # Revalidate after potentially slow body reads and worker startup.
        # A reset, suspension, logout or workspace switch may have completed
        # since the initial middleware check.
        await asyncio.to_thread(store.validate_dispatch,request.cookies.get(COOKIE),identity['workspace_id'])
        headers={'x-offerpath-worker':worker.token}
        for name in ('accept','content-type'):
            if name in request.headers:headers[name]=request.headers[name]
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=660) as client:
                result=await client.request(request.method,f'http://127.0.0.1:{worker.port}/{path}',params=list(request.query_params.multi_items()),content=body,headers=headers)
        except httpx.HTTPError:raise HTTPException(503,'Workspace connection interrupted. Reload before retrying an email send.')
        # No worker cookies, redirects or internal headers cross the trust boundary.
        response_headers={k:v for k,v in result.headers.items() if k.lower() in ('content-type','content-disposition','retry-after')}
        return Response(result.content,status_code=result.status_code,headers=response_headers)

    return app
