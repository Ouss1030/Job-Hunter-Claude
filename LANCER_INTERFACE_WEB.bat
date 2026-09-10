@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Maquette de la nouvelle interface (Starlette + Jinja2).
rem L'ancienne interface Streamlit reste disponible via START_JOBHUNTER.bat.

if exist ".venv\Scripts\python.exe" (
    set "PY=%CD%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python introuvable.
        pause
        exit /b 1
    )
    set "PY=python"
)

echo.
echo   JobHunter - interface web (maquette)
echo   http://127.0.0.1:8600
echo.
start "" "http://127.0.0.1:8600"
"%PY%" -m webui.serveur
pause
