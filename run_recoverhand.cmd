@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [RecoverHand] First run: preparing the Python 3.11 environment...
    call "%~dp0setup_dev.cmd"
    if errorlevel 1 (
        echo.
        echo [RecoverHand] Setup failed. See the Chinese development guide in this folder.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m recoverhand_host.desktop
if errorlevel 1 (
    echo.
    echo [RecoverHand] The application exited with an error. Run verify_dev.cmd for diagnostics.
    pause
    exit /b 1
)
endlocal
