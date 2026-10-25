[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WienerKingdom.Local.ps1')
try {
    $listener = Get-WienerKingdomListener
    if (-not $listener) { Write-Host 'Wiener Kingdom ya esta detenido.'; exit 0 }
    # Revalidate immediately before stopping; never trust a stale PID file.
    $current = Get-WienerKingdomListener
    if (-not $current -or $current.ProcessId -ne $listener.ProcessId -or
        $current.CreationDate -ne $listener.CreationDate) {
        throw 'El proceso cambio durante la comprobacion. No se detuvo ningun proceso.'
    }
    Stop-Process -Id $current.ProcessId -ErrorAction Stop
    Write-Host 'Servidor local de Wiener Kingdom detenido.'
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
