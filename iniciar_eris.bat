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
rem segundo plano via pythonw.exe, cada uma sob eris/watchdog.py - que
rem reinicia sozinho com backoff se a instancia cair sem avisar (2026-08-30,
rem pedido do usuario: "o bot de musica ficava caindo direto... quero evitar
rem isso tbm"). Controle pelo icone (so o papel "completo" mostra um -
rem "musica" e controlada a distancia por ele, ver eris/tray.py). Logs vao
rem pra logs\AAAA-MM-DD.log (as 2 instancias, mesmo arquivo); o watchdog em
rem si loga em logs\watchdog_completo.log/watchdog_musica.log.
rem Pra debug com console de verdade, SEM watchdog nem tray:
rem ".venv\Scripts\python.exe -m eris.main" (ou "... musica") direto neste
rem terminal.

if not exist "logs" mkdir "logs"

echo Iniciando ERIS (completo + musica) em segundo plano - use o icone na bandeja do sistema.
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog < nul >> "logs\watchdog_completo.log" 2>&1
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog musica < nul >> "logs\watchdog_musica.log" 2>&1
