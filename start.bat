@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Mediul nu e configurat. Ruleaza intai setup.bat
  echo.
  pause
  exit /b 1
)
.venv\Scripts\python run_desktop.py
