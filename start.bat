@echo off
setlocal
pushd "%~dp0" || exit /b 1
python -m mailcheck.web.supervisor %*
set "offerpath_exit_code=%errorlevel%"
popd
exit /b %offerpath_exit_code%
