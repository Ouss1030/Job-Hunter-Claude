@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Expansion des sources : audit hors ligne, decouverte d'employeurs,
rem matrice de couverture et paquet de diagnostic. Aucun run de collecte.

set "PY="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import requests, bs4" >nul 2>&1
    if not errorlevel 1 set "PY=%CD%\.venv\Scripts\python.exe"
)
if not defined PY (
    python -c "import requests, bs4" >nul 2>&1
    if errorlevel 1 goto :manque
    set "PY=python"
)

:menu
echo.
echo  ============================================================
echo    JOBHUNTER - EXPANSION DES SOURCES
echo  ============================================================
echo    Interpreteur : %PY%
echo.
echo    1. Audit hors ligne (39 tests, aucun reseau, ~10 s)
echo    2. Decouverte : passer les graines au moteur (reseau, ~15 min)
echo    3. Decouverte : un ou plusieurs domaines que vous tapez
echo    4. Matrice de couverture + paquet de diagnostic (ZIP)
echo    5. Etat du registre des employeurs decouverts
echo    Q. Quitter
echo.
set /p "CHOIX=  Votre choix : "
if /i "%CHOIX%"=="1" goto :audit
if /i "%CHOIX%"=="2" goto :graines
if /i "%CHOIX%"=="3" goto :domaines
if /i "%CHOIX%"=="4" goto :matrice
if /i "%CHOIX%"=="5" goto :registre
if /i "%CHOIX%"=="Q" exit /b 0
goto :menu

:audit
"%PY%" -m diagnostics.expansion_sources_v1_audit
echo.
pause
goto :menu

:graines
echo.
echo   Chaque domaine coute 1 a 10 requetes ; les resultats vont dans
echo   exports\logs\discovery_^<horodatage^>\ et config\ats_employers_v2.json
echo.
"%PY%" -m sources.source_discovery_v1
echo.
pause
goto :menu

:domaines
echo.
set /p "DOMS=  Domaines separes par des espaces (ex. ucb.com jobs.gent.be) : "
if "%DOMS%"=="" goto :menu
"%PY%" -m sources.source_discovery_v1 %DOMS%
echo.
pause
goto :menu

:matrice
"%PY%" -m diagnostics.source_coverage_matrix
"%PY%" -m diagnostics.expansion_diag_pack
echo.
pause
goto :menu

:registre
"%PY%" -c "from sources.ats_employers_v2 import charger, resume; import json; d=charger(); print(json.dumps(resume(), ensure_ascii=False)); [print(f\"  {e['ats']:<16} {str(e['identifier'])[:44]:<44} {e['label'][:28]:<28} BE={e.get('jobs_be')}\") for e in d['employers']]"
echo.
pause
goto :menu

:manque
echo.
echo   Aucun interpreteur ne dispose de requests et beautifulsoup4.
echo   Lancez : pip install -r requirements.txt
echo.
pause
exit /b 1
