# Watchdog del bot Scalping XAUUSD en el VPS: mantiene vivos el bot y la sombra; relanza si mueren.
#   Ensayo (solo lee datos):  powershell -ExecutionPolicy Bypass -File deploy\start_vps.ps1
#   REAL (dinero real):       powershell -ExecutionPolicy Bypass -File deploy\start_vps.ps1 -Mode live
#   Comprobar sin lanzar:     ... -DryRun   (dice qué haría y sale; seguro en cualquier máquina)
# NUNCA lo arranques en dos máquinas a la vez: el instance.lock del bot es local y no ve al otro PC.
param(
    [ValidateSet("observe", "live")] [string]$Mode = "observe",
    [string]$Terminal = "",          # ruta de terminal64.exe; vacío = no lo arranca (lo abre el inicio de Windows)
    [int]$EverySec = 30,
    [switch]$DryRun
)
$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Repo "logs\watchdog.log"
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
function Say($m) { $l = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m; Write-Host $l; Add-Content -Path $Log -Value $l -Encoding utf8 }
function Py { Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -notmatch 'multiprocessing-fork' } }
function Start-Py($argv, [bool]$live) {
    $env:PYTHONIOENCODING = "utf-8"
    if ($live) { $env:ALLOW_LIVE_TRADING = "1" } else { Remove-Item Env:ALLOW_LIVE_TRADING -ErrorAction SilentlyContinue }
    $p = Start-Process -FilePath python -ArgumentList $argv -WorkingDirectory $Repo -WindowStyle Hidden -PassThru
    Remove-Item Env:ALLOW_LIVE_TRADING -ErrorAction SilentlyContinue   # solo lo hereda ese proceso
    Say "lanzado PID $($p.Id): python $($argv -join ' ')"
}

Say "watchdog iniciado (modo $Mode, repo $Repo)"
while ($true) {
    if ($Terminal -and -not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
        if ($DryRun) { Say "[dry] abriría MT5" } else { Start-Process -FilePath $Terminal; Say "MT5 abierto"; Start-Sleep 60 }
    }
    $ps = @(Py)
    # bot = launcher run.py oro_scalping, su main.py hijo u observe.py; cualquiera cuenta como "ya hay bot"
    $bot = @($ps | Where-Object { $_.CommandLine -match 'oro_scalping|\smain\.py|observe\.py' })
    $sim = @($ps | Where-Object { $_.CommandLine -match 'sim_parallel' })
    if ($bot.Count -eq 0) {
        $argv = if ($Mode -eq "live") { @("run.py", "oro_scalping") } else { @("xauusd_scalping_bot\observe.py") }
        if ($DryRun) { Say "[dry] lanzaría el bot ($Mode)" } else { Start-Py $argv ($Mode -eq "live") }
    }
    if ($sim.Count -eq 0) {
        if ($DryRun) { Say "[dry] lanzaría la sombra" } else { Start-Py @("run.py", "sim_parallel") $false }
    }
    if ($DryRun) { Say "[dry] bot: $($bot.ProcessId -join ',') | sombra: $($sim.ProcessId -join ',')"; break }
    Start-Sleep $EverySec
}
