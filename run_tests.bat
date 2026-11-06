@echo off
rem Run the automated tests. Desktop tests (real keyboard/mouse input) are opt-in:
rem   run_tests.bat --desktop
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || python -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt || exit /b 1
if /i "%~1"=="--desktop" (
  set TEXTSNAP_DESKTOP_TESTS=1
  shift
)
".venv\Scripts\python.exe" -m pytest tests -q -p no:cacheprovider %1 %2 %3 %4 %5
exit /b %ERRORLEVEL%
