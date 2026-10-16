Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Start monitor server silently if not running
WshShell.Run "pythonw """ & scriptDir & "\monitor-server.py""", 0, False
WScript.Sleep 2000

' Launch the desktop widget
WshShell.Run "pythonw """ & scriptDir & "\desktop-widget.pyw""", 0, False
