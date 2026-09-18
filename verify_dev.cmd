@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "RECOVERHAND_PY=.venv\Scripts\python.exe"
if not exist "%RECOVERHAND_PY%" (
    echo [ERROR] .venv does not exist. Run setup_dev.cmd first.
    exit /b 1
)

echo [1/4] Checking Python, Qt Widgets, Qt WebEngine, and PyQtGraph...
"%RECOVERHAND_PY%" -c "import sys, PySide6, pyqtgraph; from PySide6.QtWebEngineWidgets import QWebEngineView; print('Python', sys.version.split()[0], '/ PySide6', PySide6.__version__, '/ PyQtGraph', pyqtgraph.__version__, '/ QtWebEngine OK')"
if errorlevel 1 exit /b 2

echo [2/4] Running automated tests...
"%RECOVERHAND_PY%" -m pytest -q
if errorlevel 1 exit /b 3

echo [3/4] Running Ruff checks...
"%RECOVERHAND_PY%" -m ruff check backend tests
if errorlevel 1 exit /b 4

echo [4/4] Checking Python bytecode compilation...
"%RECOVERHAND_PY%" -m compileall -q backend tests
if errorlevel 1 exit /b 5

echo [RecoverHand] Verification passed.
exit /b 0
