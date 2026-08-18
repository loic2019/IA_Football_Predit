@echo off
REM ============================================================================
REM start_all_hidden.bat — Lance backend (FastAPI) + frontend (Next.js)
REM ensemble, SANS fenêtres visibles (prévu pour tourner via la tâche
REM planifiée Windows, voir install_startup_task.ps1). Les logs de chacun
REM sont écrits dans logs\api_backend.log et logs\frontend.log.
REM ============================================================================

set SCRIPT_DIR=%~dp0
set FRONTEND_DIR=%SCRIPT_DIR%frontend

if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"

cd /d "%SCRIPT_DIR%"
call .venv\Scripts\activate.bat

echo [%date% %time%] Demarrage backend FastAPI >> "%SCRIPT_DIR%logs\api_backend.log"
start /b "" cmd /c "uvicorn api.main:app --port 8000 >> "%SCRIPT_DIR%logs\api_backend.log" 2>&1"

cd /d "%FRONTEND_DIR%"
echo [%date% %time%] Demarrage frontend Next.js >> "%SCRIPT_DIR%logs\frontend.log"
npm run dev >> "%SCRIPT_DIR%logs\frontend.log" 2>&1
