@echo off
REM Double-click this file to open Braid.
setlocal

cd /d "%~dp0.."

echo Starting Braid...
echo.

set "PYTHON="
for %%P in (py python python3) do (
  if not defined PYTHON (
    %%P -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON=%%P"
  )
)

if not defined PYTHON (
  echo Braid needs Python 3.9 or newer, and none was found.
  echo.
  echo Install it from https://www.python.org/downloads/
  echo During installation, tick "Add Python to PATH".
  echo.
  echo Then double-click this file again.
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

%PYTHON% -m braid --version >nul 2>&1
if errorlevel 1 (
  echo Could not start Braid from %CD%.
  echo Make sure this file is still inside the folder you unzipped.
  echo.
  pause
  exit /b 1
)

echo Braid is opening in your browser.
echo Leave this window open while you use it. Close it to stop braid.
echo.

%PYTHON% -m braid serve

echo.
echo Braid has stopped.
pause
