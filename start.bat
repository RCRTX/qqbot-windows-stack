@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" tools\stack.py start %*
set "STACK_RESULT=%errorlevel%"
if not "%STACK_RESULT%"=="0" goto done
start "" http://127.0.0.1:8090
:done
pause
exit /b %STACK_RESULT%
