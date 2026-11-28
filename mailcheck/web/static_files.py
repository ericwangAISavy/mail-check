"""Static files with consistent invalid-path handling across Windows and POSIX."""
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse


_WINDOWS_DEVICES = {'CON','PRN','AUX','NUL','CONIN$','CONOUT$'} | {
    prefix+number for prefix in ('COM','LPT') for number in '123456789¹²³'
}


class PortableStaticFiles(StaticFiles):
    async def __call__(self,scope,receive,send):
        started=False
        pending=None
        # Open/read files before committing headers, including on servers that
        # otherwise offer a path-send shortcut that opens the file afterward.
        if 'http.response.pathsend' in scope.get('extensions',{}):
            scope={**scope,'extensions':{key:value for key,value in scope['extensions'].items() if key!='http.response.pathsend'}}
        async def delayed_send(message):
            nonlocal started,pending
            if message['type']=='http.response.start':
                pending=message
                return
            if pending is not None:
                started=True
                await send(pending)
                pending=None
            await send(message)
        try:
            await super().__call__(scope,receive,delayed_send)
        except FileNotFoundError:
            if started:raise
            # A deployment can remove an old hashed asset after lookup but
            # before opening it. Return a complete error, never a truncated 200.
            await PlainTextResponse('Not found',status_code=404,headers={'Cache-Control':'no-store'})(scope,receive,send)

    async def get_response(self, path, scope):
        # A stack location such as bundle.js:267:43834 is not a file URL.
        # Reject Windows-invalid path characters before touching the filesystem;
        # colons must also never reach Windows alternate-data-stream lookup.
        # Starlette normalizes URL separators to backslashes on Windows.
        # Reject backslashes in the original URL, not normalized file paths.
        if '\\' in scope.get('path','') or any(ord(char)<32 or ord(char)==127 or char in ':<>"|?*' for char in path):
            raise HTTPException(status_code=404)
        for part in path.replace('\\','/').split('/'):
            if part in ('','.','..'):continue
            if part.endswith((' ','.')) or part.split('.',1)[0].rstrip(' ').upper() in _WINDOWS_DEVICES:
                raise HTTPException(status_code=404)
        try:
            return await super().get_response(path,scope)
        except OSError as exc:
            # ERROR_INVALID_NAME, ERROR_BAD_PATHNAME, filename too long.
            # Leave disk failures and unexpected OS errors visible to operators.
            if getattr(exc,'winerror',None) in (123,161,206):
                raise HTTPException(status_code=404) from None
            raise


#: Text assets worth compressing; images and fonts are already compressed.
_COMPRESSIBLE = ('.js', '.mjs', '.css', '.svg', '.json', '.map', '.txt', '.html', '.webmanifest')


class CompressedStaticFiles:
    """Gzip text assets on their way out.

    Through a Cloudflare tunnel the hop from this server to Cloudflare can be
    slow, and every new build starts with a cold edge cache: an uncompressed
    560 KB bundle could take over a minute and trip the startup timeout.
    Compressing cuts that to about a third, and Cloudflare caches the result.
    Range requests are passed through untouched, since a gzip body cannot
    satisfy a byte range of the original file.
    """

    def __init__(self, static_app, *, minimum_size=1024, compresslevel=6):
        from starlette.middleware.gzip import GZipMiddleware
        self.static_app = static_app
        self.gzip = GZipMiddleware(static_app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path', '').lower().endswith(_COMPRESSIBLE) \
                and not any(name == b'range' for name, _ in scope.get('headers', [])):
            await self.gzip(scope, receive, send)
        else:
            await self.static_app(scope, receive, send)
