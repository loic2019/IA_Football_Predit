# ==============================================================================
# install_startup_task.ps1 — Installe une tâche planifiée Windows qui démarre
# le backend FastAPI + le frontend Next.js automatiquement à chaque ouverture
# de session, de façon invisible. Même méthode fiable que celle déjà utilisée
# pour "CongobetAutoCycleWorker" (via wscript + .vbs, pas le paramètre -Hidden
# du Planificateur qui provoque un arrêt immédiat sur les scripts .bat).
#
# Utilisation (PowerShell EN ADMINISTRATEUR, obligatoire pour créer une tâche) :
#   cd C:\Users\LOBEZOS\Downloads\Scrapper_2
#   powershell -ExecutionPolicy Bypass -File install_startup_task.ps1
#
# Pour désinstaller :
#   Unregister-ScheduledTask -TaskName "CongobetFullStack" -Confirm:$false
# ==============================================================================

$ErrorActionPreference = "Stop"

$TaskName   = "CongobetFullStack"
$ProjectDir = $PSScriptRoot
$VbsPath    = Join-Path $ProjectDir "run_full_stack_hidden.vbs"

if (-not (Test-Path $VbsPath)) {
    Write-Host "ERREUR : $VbsPath introuvable. Lance ce script depuis le dossier du projet." -ForegroundColor Red
    exit 1
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "Lance le backend FastAPI + frontend Next.js au demarrage de session, en arriere-plan." `
    | Out-Null

Write-Host ""
Write-Host "Tache planifiee '$TaskName' installee avec succes." -ForegroundColor Green
Write-Host "Backend + frontend demarreront automatiquement a chaque ouverture de session Windows."
Write-Host ""
Write-Host "Pour la lancer MAINTENANT sans attendre le prochain logon :"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "Logs : $ProjectDir\logs\api_backend.log et $ProjectDir\logs\frontend.log"
Write-Host "Interface : http://localhost:3000  (backend : http://localhost:8000)"
