@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "RECOVERHAND_PY=.venv\Scripts\python.exe"
if not exist "%RECOVERHAND_PY%" (
    call setup_dev.cmd devices
    if errorlevel 1 exit /b 1
)

"%RECOVERHAND_PY%" -c "import bleak" >nul 2>nul
if errorlevel 1 (
    echo [RecoverHand] Installing the optional BLE dependency...
    "%RECOVERHAND_PY%" -m pip install -c constraints-dev-win-py311.txt -e ".[emg]"
    if errorlevel 1 exit /b 1
)

"%RECOVERHAND_PY%" -m recoverhand_host.emg_monitor
exit /b %errorlevel%
