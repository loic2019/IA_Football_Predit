@echo off
REM ============================================================================
REM start_auto_cycle_worker.bat — Lance auto_cycle_worker.py en arrière-plan
REM ============================================================================
REM Ce script :
REM   1. Se place dans le dossier du projet (peu importe d'où il est appelé,
REM      y compris depuis le Planificateur de tâches Windows).
REM   2. Utilise le Python de l'environnement virtuel .venv du projet.
REM   3. Relance automatiquement le worker s'il plante, avec les logs dans
REM      logs\auto_cycle_worker.log (utile pour diagnostiquer sans terminal
REM      visible, puisque le Planificateur de tâches le lance caché).
REM ============================================================================

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

:loop
echo [%date% %time%] Demarrage auto_cycle_worker.py >> logs\auto_cycle_worker.log
".venv\Scripts\python.exe" auto_cycle_worker.py >> logs\auto_cycle_worker.log 2>&1
echo [%date% %time%] Worker arrete (code %errorlevel%) - redemarrage dans 15s >> logs\auto_cycle_worker.log
timeout /t 15 /nobreak >nul
goto loop
