@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Interface web (Starlette + Jinja2 + uvicorn).
rem L'ancienne interface Streamlit reste disponible via START_JOBHUNTER.bat.

rem Choix de l'interpreteur : le .venv s'il sait importer les modules de
rem l'interface, sinon le Python global. Le .venv peut exister sans avoir
rem recu INSTALL_UI.bat — il ne contient alors que le pipeline, et le
rem choisir aveuglement echoue sur ModuleNotFoundError.
set "PY="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import uvicorn, starlette, jinja2" >nul 2>&1
    if not errorlevel 1 set "PY=%CD%\.venv\Scripts\python.exe"
)
if not defined PY (
    python -c "import uvicorn, starlette, jinja2" >nul 2>&1
    if errorlevel 1 goto :manque
    set "PY=python"
)

echo.
echo   JobHunter - interface web
echo   Interpreteur : %PY%
echo   http://127.0.0.1:8600
echo.
start "" "http://127.0.0.1:8600"
"%PY%" -m webui.serveur
pause
exit /b 0

:manque
echo.
echo   Aucun interpreteur ne dispose des modules de l'interface
echo   (uvicorn, starlette, jinja2).
echo.
echo   Lancez INSTALL_UI.bat une fois, puis relancez ce script.
echo.
pause
exit /b 1
