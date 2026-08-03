@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo    Volume Profile Terminal - Setup
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [EROARE] Python nu e gasit in PATH.
  echo          Instaleaza Python 3.14 de pe python.org
  echo          si bifeaza "Add Python to PATH", apoi ruleaza din nou.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo Gasit: %%v
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Creez mediul virtual .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [EROARE] Nu am putut crea .venv
    pause
    exit /b 1
  )
) else (
  echo .venv exista deja - sar peste creare.
)
echo.

echo Actualizez pip ...
.venv\Scripts\python -m pip install --upgrade pip >nul 2>&1

echo Instalez pachetele (versiuni exacte) ...
.venv\Scripts\pip install -r requirements-lock.txt
if errorlevel 1 (
  echo.
  echo Versiunile exacte nu s-au potrivit ^(alta versiune de Python?^).
  echo Incerc versiuni compatibile din requirements.txt ...
  .venv\Scripts\pip install -r requirements.txt
  if errorlevel 1 (
    echo [EROARE] Instalarea pachetelor a esuat.
    pause
    exit /b 1
  )
)
echo.

echo Instalez proiectul ^(editabil^) ...
.venv\Scripts\pip install -e .
echo.

echo ============================================
echo    Gata! Pornesc aplicatia...
echo    ^(data viitoare foloseste start.bat^)
echo ============================================
echo.
.venv\Scripts\python run_desktop.py
pause
