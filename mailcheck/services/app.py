"""Infrastructure health only until domain migration contracts are implemented."""
import asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mailcheck import __version__
from mailcheck.web.security import install_http_boundary


def create_service_app(settings,probe=None):
    app=FastAPI(title=f'OfferPath {settings.role}',docs_url=None,redoc_url=None,openapi_url=None)
    if probe is None:
        from .dependencies import probe_dependencies
        async def probe():return await probe_dependencies(settings)

    @app.get('/health/live')
    async def live():return {'service':settings.role,'version':__version__,'phase':'foundation','business_ready':False}

    @app.get('/health/dependencies')
    async def dependencies():
        try:
            async with asyncio.timeout(4):state=await probe()
        except Exception:state={'postgres':False,'rabbitmq':False}
        ok=bool(state.get('postgres') and state.get('rabbitmq'))
        return JSONResponse({'service':settings.role,'phase':'foundation','business_ready':False,'infrastructure_ready':ok,'dependencies':state},200 if ok else 503)

    @app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
    async def not_migrated(path:str):
        return JSONResponse({'error':'Microservice business migration is not ready. Continue using the existing OfferPath deployment.','code':'migration_not_ready'},503,headers={'Retry-After':'60'})

    install_http_boundary(app)
    return app
