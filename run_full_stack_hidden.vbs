' ==============================================================================
' run_full_stack_hidden.vbs — Lance start_all_hidden.bat de façon TOTALEMENT
' invisible (aucune fenêtre console), même technique que run_hidden.vbs déjà
' utilisé pour le worker de scraping (évite le bug STATUS_CONTROL_C_EXIT du
' Planificateur de tâches Windows avec les scripts .bat/cmd.exe).
' ==============================================================================

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
BatPath = ScriptDir & "\start_all_hidden.bat"

WshShell.Run """" & BatPath & """", 0, False
