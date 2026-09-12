@echo off
setlocal EnableExtensions
cd /d "%~dp0"

chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "exports\logs\ui" mkdir "exports\logs\ui" >nul 2>&1
set "STARTLOG=%CD%\exports\logs\ui\startup_ui.log"

echo ============================================================ > "%STARTLOG%"
echo JobHunter UI - journal de demarrage >> "%STARTLOG%"
echo Date : %DATE% %TIME% >> "%STARTLOG%"
echo Dossier : %CD% >> "%STARTLOG%"
echo ============================================================ >> "%STARTLOG%"

rem Si Streamlit est deja lance sur 8501, ne pas tenter un deuxieme serveur.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$p=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; Write-Output ('PORT_8501_IN_USE PID=' + $c.OwningProcess + ' PROCESS=' + $p.ProcessName); exit 10}else{exit 0}" >> "%STARTLOG%" 2>&1
if "%ERRORLEVEL%"=="10" goto :port_in_use

rem Le .venv n'est retenu que s'il sait importer streamlit. Il peut exister
rem sans avoir recu INSTALL_UI.bat — il ne contient alors que le pipeline,
rem et le choisir aveuglement echoue sur ModuleNotFoundError.
set "PY="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import streamlit, pandas" >nul 2>&1
    if not errorlevel 1 set "PY=%CD%\.venv\Scripts\python.exe"
)
if not defined PY (
    where python >nul 2>&1
    if errorlevel 1 goto :no_python
    python -c "import streamlit, pandas" >nul 2>&1
    if errorlevel 1 goto :no_python
    set "PY=python"
)

echo Python choisi : %PY% >> "%STARTLOG%"

echo.
echo ================================================
echo JobHunter - demarrage de l'interface
echo ================================================
echo Dossier : %CD%
echo Python  : %PY%
echo.

"%PY%" --version >> "%STARTLOG%" 2>&1
if errorlevel 1 goto :python_error

"%PY%" -c "import streamlit, sys; print('Python executable:', sys.executable); print('Streamlit:', streamlit.__version__)" >> "%STARTLOG%" 2>&1
if errorlevel 1 goto :streamlit_error

if not exist "jobhunter_ui.py" goto :missing_ui

"%PY%" -m compileall -q "jobhunter_ui.py" "interface" >> "%STARTLOG%" 2>&1
if errorlevel 1 goto :compile_error

echo Verification OK. Lancement de Streamlit... >> "%STARTLOG%"
echo Verification OK. Lancement de Streamlit...
echo.
echo IMPORTANT : laisse cette fenetre ouverte tant que tu utilises JobHunter.
echo Si l'interface ne s'ouvre pas, le message d'erreur restera visible ici.
echo.

"%PY%" -m streamlit run "jobhunter_ui.py" --server.address 127.0.0.1 --server.port 8501
set "RC=%ERRORLEVEL%"

echo. >> "%STARTLOG%"
echo Streamlit s'est arrete avec le code %RC%. >> "%STARTLOG%"
echo.
echo ============================================================
echo Streamlit s'est arrete avec le code %RC%.
echo Journal : %STARTLOG%
echo ============================================================
type "%STARTLOG%"
echo.
pause
exit /b %RC%

:port_in_use
echo.
echo ================================================
echo Le port 8501 est deja utilise.
echo Une instance de JobHunter/Streamlit est probablement deja lancee.
echo ================================================
type "%STARTLOG%"
echo.
echo J'ouvre l'adresse existante dans ton navigateur.
start "" "http://127.0.0.1:8501"
echo.
echo Si ce n'est PAS JobHunter, ferme le programme indique ci-dessus puis relance ce fichier.
echo.
pause
exit /b 0

:no_python
echo ERREUR : aucun Python ne dispose de streamlit et pandas. >> "%STARTLOG%"
echo ERREUR : aucun Python ne dispose de streamlit et pandas.
echo          Lancez INSTALL_UI.bat une fois, puis relancez ce script.
goto :fail

:python_error
echo ERREUR : impossible d'executer Python. >> "%STARTLOG%"
echo ERREUR : impossible d'executer Python.
goto :fail

:streamlit_error
echo ERREUR : Streamlit n'est pas disponible dans cet environnement Python. >> "%STARTLOG%"
echo ERREUR : Streamlit n'est pas disponible dans cet environnement Python.
goto :fail

:missing_ui
echo ERREUR : jobhunter_ui.py est introuvable dans %CD%. >> "%STARTLOG%"
echo ERREUR : jobhunter_ui.py est introuvable dans %CD%.
goto :fail

:compile_error
echo ERREUR : le code de l'interface ne passe pas la verification Python. >> "%STARTLOG%"
echo ERREUR : le code de l'interface ne passe pas la verification Python.
goto :fail

:fail
echo.
echo ============================================================
echo ECHEC DU DEMARRAGE DE JOBHUNTER
echo ============================================================
echo.
type "%STARTLOG%"
echo.
echo Copie-colle ce qui est affiche ci-dessus si tu veux me l'envoyer.
echo Le meme diagnostic est dans :
echo %STARTLOG%
echo.
pause
exit /b 1
