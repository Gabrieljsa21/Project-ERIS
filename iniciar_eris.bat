@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem PYTHONUNBUFFERED=1: sem isso, a saida do Python pra arquivo (nao-TTY) fica em
rem buffer de bloco - um kill forcado do processo (Stop-Process) perde as ultimas
rem linhas que ainda nao tinham sido escritas no disco, mesmo que tenham
rem realmente acontecido. Mesmo raciocinio do iniciar_galateia.bat da GAIA.
set PYTHONUNBUFFERED=1

rem Sobe as 2 instancias do ERIS (completo + musica, ver eris/main.py) em
rem segundo plano via pythonw.exe - sem janela de terminal nenhuma. Controle
rem pelo icone de cada uma na bandeja do sistema (Ver logs/Reiniciar/Fechar,
rem ver eris/tray.py). Logs vao pra logs\AAAA-MM-DD.log.
rem Pra debug com console de verdade: ".venv\Scripts\python.exe -m eris.main"
rem (ou "... musica" pra 2a instancia) direto neste terminal.

if not exist "logs" mkdir "logs"

echo Iniciando ERIS (completo + musica) em segundo plano - use os icones na bandeja do sistema.
start "" /B ".venv\Scripts\pythonw.exe" -m eris.main
start "" /B ".venv\Scripts\pythonw.exe" -m eris.main musica
