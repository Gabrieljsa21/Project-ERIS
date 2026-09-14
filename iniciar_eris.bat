@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem PYTHONUNBUFFERED=1: sem isso, a saida do Python pra arquivo (nao-TTY) fica em
rem buffer de bloco - um kill forcado do processo (Stop-Process) perde as ultimas
rem linhas que ainda nao tinham sido escritas no disco, mesmo que tenham
rem realmente acontecido. Mesmo raciocinio do iniciar_galateia.bat da GAIA.
set PYTHONUNBUFFERED=1

rem Sobe as 2 instancias do ERIS (principal + musica, ver eris/main.py) em
rem segundo plano via pythonw.exe, cada uma sob eris/watchdog.py - que
rem reinicia sozinho com backoff se a instancia cair sem avisar (2026-08-30,
rem pedido do usuario: "o bot de musica ficava caindo direto... quero evitar
rem isso tbm"). Controle pelo icone (so o papel "principal" mostra um -
rem "musica" e controlada a distancia por ele, ver eris/tray.py). Logs vao
rem pra logs\AAAA-MM-DD.log (as 2 instancias, mesmo arquivo); o watchdog em
rem si loga em logs\watchdog_principal.log/watchdog_musica.log.
rem Pra debug com console de verdade, SEM watchdog nem tray:
rem ".venv\Scripts\python.exe -m eris.main" (ou "... musica") direto neste
rem terminal.
rem
rem Parametro opcional (2026-09-04, pedido do usuario: "tem como separar p
rem reiniciar so parte do pandora?") - "principal" ou "musica" sobe SO
rem aquele papel (deploy de PANDORA/Colecionador so precisa do "principal" -
rem ver _registrar_slash_colecao em eris/bot.py, "musica" nunca carrega
rem esse codigo); sem parametro, sobe os 2 (comportamento de sempre).

if not exist "logs" mkdir "logs"

if /i "%~1"=="musica" goto :musica
if /i "%~1"=="principal" goto :principal

echo Iniciando ERIS (principal + musica) em segundo plano - use o icone na bandeja do sistema.
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog < nul >> "logs\watchdog_principal.log" 2>&1
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog musica < nul >> "logs\watchdog_musica.log" 2>&1
goto :fim

:principal
echo Iniciando ERIS (so principal) em segundo plano.
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog < nul >> "logs\watchdog_principal.log" 2>&1
goto :fim

:musica
echo Iniciando ERIS (so musica) em segundo plano.
start "" /B ".venv\Scripts\pythonw.exe" -m eris.watchdog musica < nul >> "logs\watchdog_musica.log" 2>&1
goto :fim

:fim
