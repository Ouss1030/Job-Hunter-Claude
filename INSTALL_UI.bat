@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo JobHunter - installation interface V2
echo ========================================

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

%PY% -m pip install --upgrade pip
if errorlevel 1 goto :error
%PY% -m pip install -r requirements.txt -r requirements_ui.txt
if errorlevel 1 goto :error

echo.
echo Installation terminee.
echo Double-clique ensuite sur START_JOBHUNTER.bat
pause
exit /b 0

:error
echo.
echo ERREUR pendant l'installation.
pause
exit /b 1
