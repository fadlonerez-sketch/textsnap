@echo off
rem Build both Windows distributions and verify each with its self-test:
rem   dist\TextSnap           PyInstaller one-folder build (TextSnap.exe)
rem   dist\TextSnap-Portable  same app on the signed Python runtime (works under Smart App Control)
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  py -3 -m venv .venv || python -m venv .venv || goto :error
)
"%PY%" -m pip install -q -r requirements-dev.txt || goto :error

echo [1/6] Checking the bundled OCR engine...
if not exist "vendor\tesseract\tesseract.exe" goto :novendor
for %%L in (heb eng) do (
  if not exist "vendor\tesseract\tessdata\best\%%L.traineddata" goto :novendor
  if not exist "vendor\tesseract\tessdata\fast\%%L.traineddata" goto :novendor
)
"%PY%" tools\prepare_vendor.py --verify || goto :error

echo [2/6] Icon and license files...
if not exist "assets\textsnap.ico" "%PY%" tools\make_icon.py || goto :error
"%PY%" tools\collect_licenses.py build\licenses || goto :error

echo [3/6] Running PyInstaller...
if exist "dist\TextSnap" rmdir /s /q "dist\TextSnap"
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN textsnap.spec || goto :error

echo [4/6] Verifying dist\TextSnap\TextSnap.exe (self-test with synthetic images)...
"%PY%" tools\verify_build.py
set EXE_RESULT=%ERRORLEVEL%
if "%EXE_RESULT%"=="1" goto :error

echo [5/6] Building dist\TextSnap-Portable (signed Python runtime)...
"%PY%" tools\build_portable.py || goto :error

echo [6/6] Verifying dist\TextSnap-Portable...
"%PY%" tools\verify_build.py --portable || goto :error

echo.
echo Done.
echo   dist\TextSnap\TextSnap.exe
echo   dist\TextSnap-Portable\TextSnap.bat
if "%EXE_RESULT%"=="3" echo NOTE: Windows application control blocked TextSnap.exe on this PC - use TextSnap-Portable here.
exit /b 0

:novendor
echo The OCR engine is missing from vendor\tesseract.
echo Run:  %PY% tools\prepare_vendor.py
exit /b 1
:error
echo BUILD FAILED
exit /b 1
