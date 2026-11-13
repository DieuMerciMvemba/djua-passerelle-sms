@echo off
setlocal
cd /d "%~dp0\.."

set "PYTHON_BIN=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_BIN=.venv\Scripts\python.exe"

"%PYTHON_BIN%" "scripts\install_autostart.py" --action install %*
pause
