"""Static files with consistent invalid-path handling across Windows and POSIX."""
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class PortableStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        # A stack location such as bundle.js:267:43834 is not a file URL.
        # Reject Windows-invalid path characters before touching the filesystem;
        # colons must also never reach Windows alternate-data-stream lookup.
        if any(ord(char)<32 or ord(char)==127 or char in ':<>"|?*\\' for char in path):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path,scope)
        except OSError as exc:
            # ERROR_INVALID_NAME, ERROR_BAD_PATHNAME, filename too long.
            # Leave disk failures and unexpected OS errors visible to operators.
            if getattr(exc,'winerror',None) in (123,161,206):
                raise HTTPException(status_code=404) from None
            raise
