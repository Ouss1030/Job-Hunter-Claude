@echo off
setlocal
cd /d "%~dp0"
title JobHunter - Test Jobat
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Python du projet introuvable : .venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

echo Test minimal de JOBAT...
echo Ce test ne modifie PAS la base SQLite.
echo.
".venv\Scripts\python.exe" "diagnostics\jobat_v1_live_test.py"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
    echo [ERREUR] Le test Jobat a echoue. Code : %RC%
) else (
    echo [OK] Jobat fonctionne.
)
echo.
pause
exit /b %RC%
