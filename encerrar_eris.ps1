# Encerra as instancias do ERIS (principal + musica) rodando via pythonw.exe
# (ver iniciar_eris.bat) - equivalente de emergencia ao "Fechar" do icone da
# bandeja (eris/tray.py), pra quando a bandeja nao estiver acessivel.
#
# So mira processos cujo CommandLine contem o caminho do projeto (ou
# "eris.main"), pra nunca matar por engano um outro processo Python do
# usuario que nao seja do ERIS. Mesmo padrao do encerrar_galateia.ps1 da
# GAIA.
#
# -Papel principal|musica (2026-09-04, pedido do usuario: "tem como separar
# p reiniciar so parte do pandora?") - PANDORA/Colecionador so carrega no
# papel "principal" (`eris/bot.py::iniciar_bot`, `_registrar_slash_colecao`
# so roda `if principal:`) - deploy de PANDORA nunca precisa derrubar o
# "musica" (que so tem /musica e /caos), entao a musica tocando na call
# nunca precisa parar por causa disso. Sem o parametro, mata os 2 (
# comportamento de sempre).
param(
    [ValidateSet("principal", "musica", "todos")]
    [string]$Papel = "todos"
)

$pattern = 'Project-ERIS|eris\.main|eris\.watchdog'

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @('python.exe', 'pythonw.exe')) -and $_.CommandLine -and ($_.CommandLine -match $pattern)
}
if ($Papel -eq "principal") {
    $targets = $targets | Where-Object { $_.CommandLine -notmatch 'musica' }
} elseif ($Papel -eq "musica") {
    $targets = $targets | Where-Object { $_.CommandLine -match 'musica' }
}

if (-not $targets) {
    Write-Host "Nada do ERIS (papel: $Papel) estava rodando."
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

Write-Host "ERIS encerrado (papel: $Papel)."
