"""Network-facing multi-workspace gateway; business APIs execute in isolated workers."""
from __future__ import annotations
import asyncio
import threading
from contextlib import asynccontextmanager, suppress
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect
from pydantic import BaseModel, Field

from ..bidder_access import BidderAccess, viewer_read_allowed
from ..maintenance import MaintenanceLock, lock_path
from ..backups import BackupLayout
from ..backup_manager import BackupManager
from .. import config
from ..control_store import ControlStore, RevokedSession
from ..workspace_workers import InstanceLock, WorkerPool
from .auth import AuthStore, AuthFileError

COOKIE='offerpath_session'
HERE=Path(__file__).parent


class _NoWorkerCookies(DefaultCookiePolicy):
    """Connections are shared across ports/workspaces; credentials never are."""
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class Login(BaseModel):
    username: str = Field(default='owner',max_length=64)
    password: str = Field(min_length=1,max_length=256)
    role: str = Field(default='admin',max_length=16)
    bidder_id: int | None = Field(default=None,ge=1)


class BidderPassword(BaseModel):
    password: str | None = Field(default=None,min_length=12,max_length=256)
    enabled: bool = True


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
    store=store or ControlStore(config.control_dir(),AuthStore(lambda:original_auth),max_workspaces)
    pool=pool or WorkerPool(store,gateway_url,(original_config,original_db,original_auth))
    backup_manager=BackupManager(BackupLayout(original_config,original_db,store.root),store._lock)
    admin_change_lock=threading.Lock()
    bidder_access=BidderAccess(store)
    model_slots=asyncio.Semaphore(1)
    leases={}
    worker_clients={}

    def new_worker_client():
        return httpx.AsyncClient(trust_env=False, timeout=660,
            cookies=CookieJar(policy=_NoWorkerCookies()),
            limits=httpx.Limits(max_connections=None, max_keepalive_connections=64, keepalive_expiry=30))

    @asynccontextmanager
    async def worker_http_client():
        loop=asyncio.get_running_loop()
        if loop in worker_clients:
            if worker_clients[loop] is None:
                worker_clients[loop]=new_worker_client()
            yield worker_clients[loop]
        else:
            # ASGI callers without lifespan (including one-shot test/browser
            # clients) must never keep transports tied to an already-closed loop.
            async with new_worker_client() as client:
                yield client

    def ensure_workspace(wid):
        # Evaluate the SQLite lookup in the same thread as worker readiness;
        # passing store.workspace(...) as a to_thread argument blocks the loop.
        return pool.ensure(store.workspace(wid))

    async def recover_leases():
        while True:
            await asyncio.sleep(5)
            for token, lease in list(leases.items()):
                if not await asyncio.to_thread(pool.authenticate_worker,lease[2]):
                    if leases.pop(token,None):lease[1].cancel();model_slots.release()

    async def backup_loop():
        while True:
            await asyncio.sleep(30)
            try:await asyncio.to_thread(backup_manager.run_due)
            except Exception:pass  # The manager retains the error and retries; never stop other workspaces.

    @asynccontextmanager
    async def lifespan(app):
        loop=asyncio.get_running_loop()
        with MaintenanceLock(lock_path(original_config)), InstanceLock(store.root/'gateway.lock'):
            worker_clients[loop]=None
            # Start independently from browser sessions, so scheduled checks survive tab closure.
            monitor=asyncio.create_task(pool.monitor()) if start_workers else None
            recovery=asyncio.create_task(recover_leases())
            backups=asyncio.create_task(backup_loop()) if start_workers else None
            try:yield
            finally:
                if backups:
                    backups.cancel()
                    with suppress(asyncio.CancelledError):await backups
                if monitor:
                    monitor.cancel()
                    with suppress(asyncio.CancelledError):await monitor
                recovery.cancel()
                with suppress(asyncio.CancelledError):await recovery
                try:
                    client=worker_clients.pop(loop,None)
                    if client is not None:
                        await client.aclose()
                finally:
                    await asyncio.to_thread(pool.close)

    app=FastAPI(title='OfferPath',docs_url=None,redoc_url=None,lifespan=lifespan)
    @app.exception_handler(ClientDisconnect)
    async def client_disconnected(request: Request, exc: ClientDisconnect):
        # A closed tab or cancelled fetch is not an application failure.
        # The peer is gone; 499 records the cancellation without a traceback.
        return Response(status_code=499)

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

    def identity_for(token):
        return store.identity(token) or bidder_access.identity(token)

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
        asset_request=path.startswith('/assets/')
        try:identity=None if asset_request else await asyncio.to_thread(identity_for,request.cookies.get(COOKIE))
        except (AuthFileError,ValueError,OSError):return JSONResponse({'error':'Owner authentication is unavailable. Restore the original sign-in file.'},503)
        request.state.identity=identity
        public=path in ('/login','/api/auth/login','/api/auth/logout','/api/auth/session','/api/auth/admins','/api/auth/bidders') or path.startswith(('/assets/','/static/'))
        if not public:
            if not identity:
                return JSONResponse({'error':'Sign in to continue.'},401) if path.startswith('/api/') else RedirectResponse('/login',303)
            expected=request.headers.get('x-offerpath-workspace')
            if not expected and request.method=='GET' and path.startswith('/api/admin/backups/file/'):
                expected=request.query_params.get('workspace')
            if path.startswith('/api/') and expected!=identity['workspace_id']:
                return JSONResponse({'error':'Workspace changed. Reload before continuing.','workspace_changed':True},409)
            if identity['must_change_password'] and path not in ('/api/auth/password','/login'):
                return JSONResponse({'error':'Change your temporary password before opening the workspace.'},403) if path.startswith('/api/') else page()
        if identity and identity['role']=='bidder' and not path.startswith(('/assets/','/static/')):
            if path not in ('/api/auth/session','/api/auth/logout') and not viewer_read_allowed(path,request.method):
                return JSONResponse({'error':'Bidder access is read-only and limited to Dashboard, Bidder management, and your Job sourcing.'},403)
        restricted_settings = path == '/settings' or path.startswith(('/api/settings','/api/rules')) or path.rstrip('/') == '/api/autocheck'
        if identity and restricted_settings and not identity['is_owner']:
            return JSONResponse({'error':'Settings are managed by the owner.'},403)
        try:response=await call_next(request)
        except RevokedSession as exc:
            response=JSONResponse({"error":str(exc)},401)
        except (ValueError,PermissionError) as exc:
            response=JSONResponse({'error':str(exc)},403 if isinstance(exc,PermissionError) else 400)
        except AuthFileError:
            response=JSONResponse({'error':'The original owner sign-in file is unavailable.'},503)
        response.headers.update({'Cache-Control':('public, max-age=31536000, immutable' if asset_request and response.status_code in (200,206,304) else 'no-store'),'X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'DENY'})
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
        if body.role not in ('admin','bidder'):raise HTTPException(401,'Choose Admin or Bidder.')
        try:
            if body.role=='bidder':
                token=await asyncio.to_thread(bidder_access.login,body.bidder_id,body.password,request.client.host if request.client else 'unknown')
            else:
                token=await asyncio.to_thread(store.login,body.username,body.password,request.client.host if request.client else 'unknown')
        except ValueError:raise HTTPException(429,'Too many sign-in attempts. Try again in a minute.',headers={'Retry-After':'60'})
        if not token:raise HTTPException(401,'Incorrect username or password.')
        # Replacing this browser's identity must invalidate in-flight old-session requests.
        store.logout(request.cookies.get(COOKIE));bidder_access.logout(request.cookies.get(COOKIE))
        return cookie(JSONResponse(identity_for(token)),token)

    @app.post('/api/auth/logout')
    def logout(request:Request):
        store.logout(request.cookies.get(COOKIE));bidder_access.logout(request.cookies.get(COOKIE))
        response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');response.delete_cookie('mailcheck_session',path='/')
        return response

    @app.post('/api/auth/password')
    def change_password(body:Password,request:Request):
        if body.role!='admin':raise HTTPException(400,'Only admin passwords are supported.')
        token=store.change_password(request.cookies.get(COOKIE),body.password,expected_workspace=request.headers.get('x-offerpath-workspace'))
        return cookie(JSONResponse({'ok':True,'message':'Password updated. Other sessions have been signed out.','session':store.identity(token)}),token)

    @app.get('/api/auth/admins')
    def admin_directory():
        return {'admins':[{'username':u['username']} for u in store.list_admins() if u['enabled']]}

    @app.get('/api/auth/bidders')
    def bidder_directory():
        return {'bidders':bidder_access.directory()}

    @app.get('/api/auth/bidders/manage')
    def managed_bidders(request:Request):
        return {'bidders':bidder_access.managed(request.cookies.get(COOKIE),request.state.identity['workspace_id'])}

    @app.post('/api/auth/bidders/{bidder_id}/password')
    async def bidder_password(bidder_id:int,body:BidderPassword,request:Request):
        identity=request.state.identity
        try:
            worker=await asyncio.to_thread(ensure_workspace,identity['workspace_id'])
            async with worker_http_client() as client:
                result=await client.get(f'http://127.0.0.1:{worker.port}/_internal/bidders/{bidder_id}',
                    headers={'x-offerpath-worker':worker.token})
        except (httpx.HTTPError,RuntimeError,OSError):
            raise HTTPException(503,'Could not load workspace bidders. Try again when the workspace is available.')
        if result.status_code==404:raise HTTPException(404,'Bidder not found in this workspace.')
        if not result.is_success:raise HTTPException(503,'Could not load workspace bidders.')
        member=result.json()
        await asyncio.to_thread(bidder_access.configure,request.cookies.get(COOKIE),identity['workspace_id'],bidder_id,member['name'],password=body.password,enabled=body.enabled)
        return {'ok':True}

    @app.post('/api/auth/presence')
    def admin_presence(request:Request):
        if request.state.identity['role']!='admin':raise HTTPException(403,'Admin access required.')
        store.record_presence(request.cookies.get(COOKIE))
        return {'ok':True}

    @app.api_route('/api/auth/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    def missing_auth(path:str):raise HTTPException(404,'Unknown authentication endpoint.')

    from .backup_routes import install as install_backups
    install_backups(app,backup_manager,owner)
    app.state.backup_manager=backup_manager

    @app.get('/api/admin/users')
    def admins(request:Request):
        owner(request)
        online=store.online_admin_ids()
        status=pool.status()
        starts=getattr(pool,"start_times",lambda:{})()
        return {'admins':[{**u,'online':u['id'] in online,'worker_started_at':starts.get(u['workspace_id']),'health':status.get(u['workspace_id'],'starting or unavailable') if u['enabled'] else 'suspended'} for u in store.list_admins()], 'max_workspaces':store.max_workspaces}

    @app.post('/api/admin/users')
    async def create_admin(body:NewAdmin,request:Request):
        identity=owner(request)
        wid=await asyncio.to_thread(store.create_admin,request.cookies.get(COOKIE),body.username,body.workspace_name,body.password,expected_workspace=request.headers.get('x-offerpath-workspace'))
        # The supervisor starts the worker; provisioning can succeed independently of mailbox setup.
        return {'ok':True,'workspace_id':wid}

    def apply_admin_update(token,user_id,body,workspace):
        # Keep committed access and runtime state ordered together. Otherwise a
        # delayed suspension can stop a workspace after a re-enable completed.
        # Run this whole blocking operation off the gateway's event loop.
        with admin_change_lock:
            wid=store.update_admin(token,user_id,enabled=body.enabled,password=body.password,expected_workspace=workspace)
            if body.enabled is False:pool.stop(wid)
            elif body.enabled is True:pool.enable(wid)

    @app.post('/api/admin/users/{user_id}')
    async def update_admin(user_id:int,body:AdminUpdate,request:Request):
        identity=owner(request)
        if body.enabled is None and body.password is None:raise HTTPException(400,'Choose a password reset or access change.')
        await asyncio.to_thread(apply_admin_update,request.cookies.get(COOKIE),user_id,body,request.headers.get('x-offerpath-workspace'))
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
        from urllib.parse import unquote
        normalized=path
        for _ in range(4):normalized=unquote(normalized)
        if any(segment in ('.','..') for segment in normalized.split('/')) or '\\' in normalized:
            raise HTTPException(400,'Invalid API path.')
        identity=request.state.identity
        global_settings=path.startswith(('api/settings','api/rules')) or path.rstrip('/')=='api/autocheck'
        if global_settings and not identity['is_owner']:raise HTTPException(403,'Settings are managed by the owner.')
        target='legacy' if global_settings else identity['workspace_id']
        body=await request.body()
        if len(body)>4_000_000:raise HTTPException(413,'Request is too large.')
        try:worker=await asyncio.to_thread(ensure_workspace,target)
        except (RuntimeError,OSError,ValueError):raise HTTPException(503,'This workspace worker is unavailable. Contact the owner or retry later.')
        # Revalidate after potentially slow body reads and worker startup.
        # A reset, suspension, logout or workspace switch may have completed
        # since the initial middleware check.
        await asyncio.to_thread(bidder_access.validate_dispatch if identity['role']=='bidder' else store.validate_dispatch,request.cookies.get(COOKIE),identity['workspace_id'])
        headers={'x-offerpath-worker':worker.token}
        if identity['role']=='bidder':
            headers['x-offerpath-viewer']='bidder'
            headers['x-offerpath-bidder']=str(identity['bidder_id'])
        for name in ('accept','content-type'):
            if name in request.headers:headers[name]=request.headers[name]
        try:
            async with worker_http_client() as client:
                result=await client.request(request.method,f'http://127.0.0.1:{worker.port}/{path}',params=list(request.query_params.multi_items()),content=body,headers=headers)
        except httpx.HTTPError:raise HTTPException(503,'Workspace connection interrupted. Reload before retrying an email send.')
        if identity['role']=='admin' and result.is_success and request.method=='POST':
            import re
            match=re.fullmatch(r'api/payments/bidders/([0-9]+)(/remove)?',path)
            if match:
                who=int(match[1])
                if match[2]:
                    await asyncio.to_thread(bidder_access.configure,request.cookies.get(COOKIE),identity['workspace_id'],who,'Removed bidder',enabled=False)
                else:
                    import json
                    await asyncio.to_thread(bidder_access.rename,identity['workspace_id'],who,json.loads(body)['name'].strip())
        if path.rstrip('/') in ('api/settings','api/autocheck') and request.method=='POST' and result.is_success:
            # Reload schedules without restarting workers or interrupting jobs.
            async def notify(workspace):
                if workspace['id']=='legacy':return
                try:
                    member=await asyncio.to_thread(pool.ensure,workspace)
                    async with worker_http_client() as client:
                        await client.post(f'http://127.0.0.1:{member.port}/_internal/settings-updated',headers={'x-offerpath-worker':member.token},timeout=5)
                except (httpx.HTTPError,RuntimeError,OSError,ValueError):pass
            workspaces=await asyncio.to_thread(store.enabled_workspaces)
            await asyncio.gather(*(notify(workspace) for workspace in workspaces))
        # No worker cookies, redirects or internal headers cross the trust boundary.
        response_headers={k:v for k,v in result.headers.items() if k.lower() in ('content-type','content-disposition','retry-after')}
        return Response(result.content,status_code=result.status_code,headers=response_headers)

    return app
