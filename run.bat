@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_VERSION="
py -3.12 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_VERSION=3.12"
if not defined PYTHON_VERSION (
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_VERSION=3.11"
)
if not defined PYTHON_VERSION (
    py -3.10 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_VERSION=3.10"
)
if not defined PYTHON_VERSION (
    echo Python 3.10, 3.11, or 3.12 is required. Install one and try again.
    pause
    exit /b 1
)

set "REBUILD_VENV=0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 10), (3, 11), (3, 12)) else 1)" >nul 2>&1
    if errorlevel 1 set "REBUILD_VENV=1"
) else if exist ".venv" set "REBUILD_VENV=1"

if "%REBUILD_VENV%"=="1" (
    echo Existing .venv uses an unsupported Python version. Preserving it as a backup...
    ren ".venv" ".venv-incompatible-%RANDOM%"
    if errorlevel 1 goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating a virtual environment...
    py -%PYTHON_VERSION% -m venv .venv
    if errorlevel 1 (
        echo Could not create a virtual environment with Python %PYTHON_VERSION%.
        goto :error
    )
)

echo Checking and installing required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Startup failed. Check the message above and your internet connection.
pause
exit /b 1