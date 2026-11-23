@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "offerpath_python=python"
if exist ".venv\Scripts\python.exe" set "offerpath_python=.venv\Scripts\python.exe"
"%offerpath_python%" -m mailcheck.web.local_monitor --restart
set "result=%errorlevel%"
popd
exit /b %result%
