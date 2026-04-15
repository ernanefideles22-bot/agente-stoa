Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & fso.BuildPath(scriptDir, "start-stoa-18000.cmd") & """", 0, False
