@echo off
rem Builds dist\F1TelemetryHub.exe (single file) with PyInstaller from the f1-telemetry conda env.
rem Override the interpreter with:  set F1TH_PYTHON=C:\path\to\python.exe
setlocal
cd /d "%~dp0"

set "PY=%F1TH_PYTHON%"
if "%PY%"=="" if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PY=%CONDA_PREFIX%\python.exe"
if "%PY%"=="" set "PY=%USERPROFILE%\miniconda3\envs\f1-telemetry\python.exe"
if not exist "%PY%" (
  echo Python not found at "%PY%".
  echo Create the env first:  conda env create -f environment.yml
  exit /b 1
)

tasklist /FI "IMAGENAME eq F1TelemetryHub.exe" 2>nul | find /I "F1TelemetryHub.exe" >nul && (
  echo F1 Telemetry Hub is running. Close its window first, then build again.
  exit /b 1
)

"%PY%" -m PyInstaller --version >nul 2>&1 || "%PY%" -m pip install pyinstaller || exit /b 1

rem conda keeps sqlite3.dll and friends in Library\bin; put it on PATH so PyInstaller bundles them
for %%I in ("%PY%") do set "ENVDIR=%%~dpI"
set "PATH=%ENVDIR%Library\bin;%ENVDIR%;%PATH%"

rem Tk is left out: the app's window is for the Mac app (window.py); the exe has its console
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console ^
  --name F1TelemetryHub ^
  --icon assets\app.ico ^
  --exclude-module tkinter ^
  --add-data "f1telemetry\web;web" ^
  --add-data "f1telemetry\circuits.json;." ^
  --add-data "GUIDE.md;." ^
  run.py || exit /b 1

echo.
echo Built %CD%\dist\F1TelemetryHub.exe
echo Your history is stored in a "data" folder next to the exe.
