# Encerra as instancias do ERIS (completo + musica) rodando via pythonw.exe
# (ver iniciar_eris.bat) - equivalente de emergencia ao "Fechar" do icone da
# bandeja (eris/tray.py), pra quando a bandeja nao estiver acessivel.
#
# So mira processos cujo CommandLine contem o caminho do projeto (ou
# "eris.main"), pra nunca matar por engano um outro processo Python do
# usuario que nao seja do ERIS. Mesmo padrao do encerrar_galateia.ps1 da
# GAIA.

$pattern = 'Project-ERIS|eris\.main'

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @('python.exe', 'pythonw.exe')) -and $_.CommandLine -and ($_.CommandLine -match $pattern)
}

if (-not $targets) {
    Write-Host "Nada do ERIS estava rodando."
    exit 0
}

foreach ($p in $targets) {
    Write-Host "Encerrando PID $($p.ProcessId) ($($p.Name))"
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    } catch {
        # processo pode ja ter morrido como filho de outro que acabamos de matar
    }
}

Write-Host "ERIS encerrado."
