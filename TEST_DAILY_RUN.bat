@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo ========================================
echo JobHunter - test Daily Run / preflight
echo ========================================
echo Python : %PY%
echo.
"%PY%" -X utf8 -u daily_run.py --check
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo PRECHECK OK - daily_run.py est executable depuis cet environnement.
) else (
    echo ECHEC PRECHECK - code %RC%.
)
echo.
pause
exit /b %RC%
