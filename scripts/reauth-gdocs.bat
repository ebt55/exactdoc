@echo off
rem ---------------------------------------------------------------------------
rem  exactdoc - re-authenticate the Google Docs oracle. Double-click to run.
rem
rem  The OAuth app is in Google's "testing" status, so its refresh token dies
rem  about 7 days after it is issued; run this whenever a live Google Docs pass
rem  needs a fresh one. It opens a browser tab for consent and writes token.json
rem  next to credentials.json.
rem
rem  Works from the main checkout and from any git worktree of it: credentials,
rem  token and the Python environment live in the MAIN checkout (found through
rem  git's common directory), while the oracle script is this checkout's own.
rem
rem    scripts\reauth-gdocs.bat           re-authenticate
rem    scripts\reauth-gdocs.bat --check   show the resolved paths, change nothing
rem ---------------------------------------------------------------------------
setlocal
title exactdoc - Google Docs re-authentication

for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "MAIN=%REPO%"
rem No --path-format=absolute here: inside for /f, cmd splits the command at
rem "=" and git receives a bare --path-format. A worktree's common dir comes
rem back absolute anyway; the main checkout's comes back as ".git", which the
rem pushd below resolves against the checkout.
for /f "usebackq delims=" %%G in (`git -C "%REPO%" rev-parse --git-common-dir 2^>nul`) do set "COMMON=%%G"
pushd "%REPO%"
if defined COMMON for %%I in ("%COMMON%\..") do set "MAIN=%%~fI"
popd

set "PY=%MAIN%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%REPO%\.venv\Scripts\python.exe"
if not defined EXACTDOC_GDOCS_CREDENTIALS set "EXACTDOC_GDOCS_CREDENTIALS=%MAIN%\credentials.json"
if not defined EXACTDOC_GDOCS_TOKEN set "EXACTDOC_GDOCS_TOKEN=%MAIN%\token.json"
set "ORACLE=%REPO%\testkit\gdocs_oracle.py"

if /i "%~1"=="--check" goto :check

if not exist "%PY%" goto :nopython
if not exist "%EXACTDOC_GDOCS_CREDENTIALS%" goto :nocreds
if not exist "%ORACLE%" goto :nooracle

rem Move the old token aside so the oracle goes straight to the browser instead
rem of trying (and failing) to refresh a dead token. Restored on failure.
if exist "%EXACTDOC_GDOCS_TOKEN%" move /y "%EXACTDOC_GDOCS_TOKEN%" "%EXACTDOC_GDOCS_TOKEN%.prev" >nul

echo.
echo  Opening a browser tab for Google consent...
echo  Sign in with the account that owns the exactdoc Drive files.
echo.
"%PY%" "%ORACLE%" auth
if errorlevel 1 goto :failed
if not exist "%EXACTDOC_GDOCS_TOKEN%" goto :failed

if exist "%EXACTDOC_GDOCS_TOKEN%.prev" del /q "%EXACTDOC_GDOCS_TOKEN%.prev"
echo.
echo  Done. A fresh token was written; it stays valid for about 7 days.
echo.
pause
exit /b 0

:failed
echo.
echo  Authentication did not complete.
if exist "%EXACTDOC_GDOCS_TOKEN%" goto :failend
if exist "%EXACTDOC_GDOCS_TOKEN%.prev" move /y "%EXACTDOC_GDOCS_TOKEN%.prev" "%EXACTDOC_GDOCS_TOKEN%" >nul
if exist "%EXACTDOC_GDOCS_TOKEN%" echo  The previous token was put back unchanged.
:failend
echo.
pause
exit /b 1

:check
echo  checkout     %REPO%
echo  main         %MAIN%
echo  python       %PY%
echo  oracle       %ORACLE%
echo  credentials  %EXACTDOC_GDOCS_CREDENTIALS%
echo  token        %EXACTDOC_GDOCS_TOKEN%
if exist "%PY%" (echo  python found) else (echo  python MISSING)
if exist "%EXACTDOC_GDOCS_CREDENTIALS%" (echo  credentials found) else (echo  credentials MISSING)
if exist "%ORACLE%" (echo  oracle found) else (echo  oracle MISSING)
exit /b 0

:nopython
echo  Python environment not found: "%PY%"
pause
exit /b 1

:nocreds
echo  credentials.json not found: "%EXACTDOC_GDOCS_CREDENTIALS%"
pause
exit /b 1

:nooracle
echo  gdocs_oracle.py not found: "%ORACLE%"
pause
exit /b 1
