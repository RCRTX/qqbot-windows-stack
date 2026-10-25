@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" tools\stack.py stop %*
set "STACK_RESULT=%errorlevel%"
pause
exit /b %STACK_RESULT%
