@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 (
    python -m venv .venv
) else (
    py -3.12 -m venv .venv
)
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\setup.py %*
if errorlevel 1 goto failed
echo Setup complete. Edit your local configs before running start.bat.
pause
exit /b 0
:failed
echo Setup failed. Install standard Python 3.12 with pip and venv, then retry.
pause
exit /b 1
