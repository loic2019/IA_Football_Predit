' ==============================================================================
' run_hidden.vbs — Lance start_auto_cycle_worker.bat de façon TOTALEMENT
' invisible (aucune fenêtre console), sans les problèmes de fiabilité du
' paramètre "Hidden" du Planificateur de tâches Windows sur les scripts .bat
' (qui provoque souvent un arrêt immédiat avec le code STATUS_CONTROL_C_EXIT).
' ==============================================================================

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
BatPath = ScriptDir & "\start_auto_cycle_worker.bat"

' 0 = fenêtre cachée, False = ne pas attendre la fin (tourne en tâche de fond)
WshShell.Run """" & BatPath & """", 0, False
