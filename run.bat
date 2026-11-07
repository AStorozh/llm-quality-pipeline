@echo off
REM One-command launcher for Windows.
REM On first run it creates a local virtual environment and installs the
REM optional dependencies; when requirements.txt changes it installs them
REM again; otherwise it just starts the app.
cd /d "%~dp0"

if not exist .venv (
  echo First run: preparing environment...
  python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
)

fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
  copy /y requirements.txt .venv\requirements.installed >nul
)

.venv\Scripts\python main.py
pause
