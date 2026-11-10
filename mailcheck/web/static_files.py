"""Static files with consistent invalid-path handling across Windows and POSIX."""
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


_WINDOWS_DEVICES = {'CON','PRN','AUX','NUL','CONIN$','CONOUT$'} | {
    prefix+number for prefix in ('COM','LPT') for number in '123456789¹²³'
}


class PortableStaticFiles(StaticFiles):
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
