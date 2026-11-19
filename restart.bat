@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "offerpath_python=python"
if exist ".venv\Scripts\python.exe" set "offerpath_python=.venv\Scripts\python.exe"
"%offerpath_python%" -m mailcheck.web.supervisor --request-restart
set "result=%errorlevel%"
if "%result%"=="3" (
    echo Starting OfferPath...
    call "%~dp0start.bat"
    goto finished
)
if not "%result%"=="0" pause
popd
exit /b %result%
:finished
set "result=%errorlevel%"
if not "%result%"=="0" pause
popd
exit /b %result%
