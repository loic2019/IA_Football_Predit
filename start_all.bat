@echo off
REM ============================================================================
REM start_all.bat — Lance le backend FastAPI ET le frontend Next.js ensemble.
REM ============================================================================
REM ⚠️ Chemins à vérifier/adapter si besoin :
set SCRIPT_DIR=%~dp0
set FRONTEND_DIR=%SCRIPT_DIR%frontend

if not exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    echo ERREUR : .venv introuvable dans %SCRIPT_DIR%
    pause
    exit /b 1
)
if not exist "%FRONTEND_DIR%\package.json" (
    echo ERREUR : frontend introuvable dans %FRONTEND_DIR%
    echo Corrige la ligne FRONTEND_DIR dans ce fichier.
    pause
    exit /b 1
)

echo Lancement du backend (FastAPI) sur http://localhost:8000 ...
start "Backend API (FastAPI)" cmd /k "cd /d "%SCRIPT_DIR%" && .venv\Scripts\activate && uvicorn api.main:app --reload --port 8000"

timeout /t 3 /nobreak >nul

echo Lancement du frontend (Next.js) sur http://localhost:3000 ...
start "Frontend (Next.js)" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

timeout /t 5 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo Les deux serveurs tournent chacun dans leur propre fenetre.
echo Ferme ces fenetres pour les arreter.
