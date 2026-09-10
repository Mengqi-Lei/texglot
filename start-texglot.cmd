@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if not exist ".venv\Scripts\python.exe" goto setup
if not exist "frontend\dist\index.html" goto setup
goto run
:setup
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv and Node.js 22.12+ first. See README.md.
  goto error
)
uv run --no-project --python 3.13 python scripts/setup.py
if errorlevel 1 goto error
:run
".venv\Scripts\python.exe" scripts/start.py %*
if errorlevel 1 goto error
exit /b 0
:error
if "%~1"=="" pause
exit /b 1
