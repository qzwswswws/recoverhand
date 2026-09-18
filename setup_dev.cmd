@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "RECOVERHAND_ENV=.venv"
set "RECOVERHAND_PY=%RECOVERHAND_ENV%\Scripts\python.exe"
set "RECOVERHAND_SPEC=.[dev]"
if /I "%~1"=="devices" set "RECOVERHAND_SPEC=.[dev,eeg,emg]"

if exist "%RECOVERHAND_PY%" goto validate_python

echo [1/4] Finding 64-bit Python 3.11...
where py >nul 2>nul
if errorlevel 1 goto try_python_command
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize.bit_length() == 63 else 1)" >nul 2>nul
if errorlevel 1 goto try_python_command
py -3.11 -m venv "%RECOVERHAND_ENV%"
if errorlevel 1 goto create_failed
goto validate_python

:try_python_command
where python >nul 2>nul
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize.bit_length() == 63 else 1)" >nul 2>nul
if errorlevel 1 goto python_missing
python -m venv "%RECOVERHAND_ENV%"
if errorlevel 1 goto create_failed

:validate_python
echo [2/4] Checking the virtual environment...
"%RECOVERHAND_PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize.bit_length() == 63 else 1)"
if errorlevel 1 goto bad_environment

echo [3/4] Installing RecoverHand and development dependencies...
"%RECOVERHAND_PY%" -m pip install --upgrade pip
if errorlevel 1 goto install_failed
"%RECOVERHAND_PY%" -m pip install -c constraints-dev-win-py311.txt -e "%RECOVERHAND_SPEC%"
if errorlevel 1 goto install_failed

echo [4/4] Running environment verification...
call "%~dp0verify_dev.cmd"
if errorlevel 1 goto verify_failed

echo.
echo [RecoverHand] Setup completed. Run run_recoverhand.cmd to start the application.
exit /b 0

:python_missing
echo.
echo [ERROR] 64-bit Python 3.11 was not found.
echo Install Python 3.11 x64 from python.org and enable Python Launcher or Add Python to PATH.
exit /b 2

:create_failed
echo.
echo [ERROR] Could not create .venv. Check folder permissions and the Python venv component.
exit /b 3

:bad_environment
echo.
echo [ERROR] The existing .venv is not based on 64-bit Python 3.11.
echo Rename or remove .venv, then run setup_dev.cmd again.
exit /b 4

:install_failed
echo.
echo [ERROR] Dependency installation failed. Check PyPI access, proxy, certificates, and disk space.
exit /b 5

:verify_failed
echo.
echo [ERROR] Dependencies were installed, but verification failed. Keep the output above for diagnosis.
exit /b 6
