@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo JOBHUNTER - NETTOYAGE CACHE JOBAT BLOQUE
ECHO ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Environnement .venv introuvable.
    echo Lance d'abord INSTALL_UI.bat si necessaire.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from sources.jobat_detail import purge_invalid_jobat_detail_cache; print(purge_invalid_jobat_detail_cache())"

echo.
echo Termine.
pause
