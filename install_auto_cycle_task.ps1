# ==============================================================================
# install_auto_cycle_task.ps1 — Installe une tâche planifiée Windows qui lance
# start_auto_cycle_worker.bat automatiquement à chaque ouverture de session,
# de façon totalement invisible (aucune fenêtre, aucune action manuelle).
# ==============================================================================
# Utilisation (clic droit sur PowerShell -> "Exécuter en tant qu'administrateur",
# PAS obligatoire mais recommandé) :
#
#   cd C:\Users\LOBEZOS\Downloads\Scrapper_2
#   powershell -ExecutionPolicy Bypass -File install_auto_cycle_task.ps1
#
# Pour désinstaller plus tard :
#   Unregister-ScheduledTask -TaskName "CongobetAutoCycleWorker" -Confirm:$false
# ==============================================================================

$ErrorActionPreference = "Stop"

$TaskName   = "CongobetAutoCycleWorker"
$ProjectDir = $PSScriptRoot
$BatPath    = Join-Path $ProjectDir "start_auto_cycle_worker.bat"
$VbsPath    = Join-Path $ProjectDir "run_hidden.vbs"

if (-not (Test-Path $BatPath)) {
    Write-Host "ERREUR : $BatPath introuvable. Lance ce script depuis le dossier du projet." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $VbsPath)) {
    Write-Host "ERREUR : $VbsPath introuvable. Lance ce script depuis le dossier du projet." -ForegroundColor Red
    exit 1
}

# Supprime une éventuelle tâche existante du même nom (réinstallation propre)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# On passe par wscript.exe + un .vbs pour lancer le .bat de façon VRAIMENT
# invisible. Le paramètre -Hidden du Planificateur de tâches, quand on lui
# donne directement un .bat/cmd.exe, tue souvent le process presque
# immédiatement (code STATUS_CONTROL_C_EXIT) — ce détour l'évite.
$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`"" -WorkingDirectory $ProjectDir

# Se déclenche à l'ouverture de session Windows (pas besoin d'être admin/boot complet)
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Redémarrage auto si le process s'arrête, tourne indéfiniment
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
    -Description "Lance le worker CongoBet (scraping + entrainement + prediction en boucle) au demarrage de session, en arriere-plan." `
    | Out-Null

Write-Host ""
Write-Host "Tache planifiee '$TaskName' installee avec succes." -ForegroundColor Green
Write-Host "Elle se lancera automatiquement a chaque ouverture de session Windows."
Write-Host ""
Write-Host "Pour la lancer MAINTENANT sans attendre le prochain logon :"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "Pour verifier qu'elle tourne :"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "Logs du worker : $ProjectDir\logs\auto_cycle_worker.log"
