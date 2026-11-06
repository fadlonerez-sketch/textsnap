@echo off
rem Launch TextSnap from source (creates the virtual environment on first run).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
exit /b 0
:error
echo Setup failed. See the messages above.
pause
exit /b 1
