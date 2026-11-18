@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "OFFERPATH_WORKER_MODE=shared"
set "OFFERPATH_API_WORKERS=2"
set "OFFERPATH_COLLECTION_WORKERS=2"
set "OFFERPATH_PUBLIC_URL=https://app.offerpath.bid"

if not defined AMQP_URL (
    echo ERROR: AMQP_URL is not set in this terminal.
    popd
    exit /b 1
)

python -m mailcheck.web.supervisor --no-open --tunnel --allow-host app.offerpath.bid --max-workspaces 30

set "offerpath_exit_code=%errorlevel%"
popd
exit /b %offerpath_exit_code%