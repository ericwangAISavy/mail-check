@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "OFFERPATH_WORKER_MODE=shared"
set "OFFERPATH_API_WORKERS=2"
set "OFFERPATH_COLLECTION_WORKERS=2"
set "OFFERPATH_PUBLIC_URL=https://app.offerpath.bid"

set "offerpath_python=python"
python -c "import pika, uvicorn, mailcheck.web.gateway" >nul 2>&1
if errorlevel 1 (
    if not exist ".venv\Scripts\python.exe" goto missing_python
    set "offerpath_python=.venv\Scripts\python.exe"
    ".venv\Scripts\python.exe" -c "import pika, uvicorn, mailcheck.web.gateway" >nul 2>&1
    if errorlevel 1 goto missing_python
)
"%offerpath_python%" -m mailcheck.web.supervisor --prompt-broker --no-open --tunnel --allow-host app.offerpath.bid --max-workspaces 30

set "offerpath_exit_code=%errorlevel%"
popd
exit /b %offerpath_exit_code%
:missing_python
echo OfferPath needs Python with the shared worker dependencies installed.
echo From this folder, run: python -m pip install -e ".[shared]"
popd
exit /b 1
