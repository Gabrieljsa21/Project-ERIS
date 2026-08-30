' Lanca o iniciar_eris.bat com a janela do console totalmente escondida - o
' .bat em si ja sobe os processos reais (pythonw.exe -m eris.main / musica)
' escondidos, mas o CONSOLE DO PROPRIO .bat (cmd.exe processando o script)
' sempre aparece quando aberto direto (ex.: atalho da area de trabalho).
' Esse .vbs existe so pra esconder esse console tambem (mesmo padrao de
' "Project G.A.I.A/assistant/iniciar_galateia_oculto.vbs").
'
' Um atalho da area de trabalho pro ERIS deve apontar pra esse arquivo, nao
' pro .bat direto.
'
' Resolve o caminho da PROPRIA pasta em tempo de execucao (mesmo padrao de
' iniciar_galateia_oculto.vbs) - funciona em qualquer maquina/pasta onde o
' projeto for clonado, sem cravar caminho no codigo.

Set objShell = CreateObject("WScript.Shell")
Set oFso = CreateObject("Scripting.FileSystemObject")
strPastaAtual = oFso.GetParentFolderName(WScript.ScriptFullName)
objShell.Run """" & strPastaAtual & "\iniciar_eris.bat""", 0, False
