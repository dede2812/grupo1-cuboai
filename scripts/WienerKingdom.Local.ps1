# Shared checks for the local-only launcher. No global settings are changed.
$wkRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$wkWeb = Join-Path $wkRoot 'web'
$wkPython = Join-Path $wkWeb '.venv\Scripts\python.exe'
$wkManage = Join-Path $wkWeb 'manage.py'
$wkUrl = 'http://127.0.0.1:8000'
$wkRuntime = Join-Path $wkRoot '.runtime'
$wkArtifacts = Join-Path $wkRoot '.artifacts'

function Get-WienerKingdomListener {
    # netstat also works on Windows installations without NetTCPIP cmdlets.
    $connections = @(& netstat.exe -ano -p tcp)
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar el puerto local 8000.' }
    $listeners = @($connections | Where-Object { $_ -match '^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+\d+\s*$' })
    if (-not $listeners.Count) { return $null }
    if ($listeners.Count -ne 1) { throw 'El puerto 8000 tiene varios procesos. No se modifico ninguno.' }
    $parts = $listeners[0].Trim() -split '\s+'
    if ($parts[1] -ne '127.0.0.1:8000') {
        throw 'El puerto 8000 esta ocupado fuera de la interfaz local. No se modifico el proceso.'
    }
    $listenerId = [int]$parts[-1]
    $listener = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerId"
    $pythonPattern = [regex]::Escape($wkPython)
    $managePattern = [regex]::Escape($wkManage)
    $expected = '^"?' + $pythonPattern + '"?\s+(?:"?' + $managePattern + '"?|manage\.py)\s+runserver\s+127\.0\.0\.1:8000\s+--noreload\s*$'
    if (-not $listener -or $listener.CommandLine -notmatch $expected) {
        throw 'El puerto 8000 pertenece a otro programa. No se inicio ni se detuvo ningun proceso.'
    }
    # A venv on Windows may launch a child process from the base Python install.
    $owner = $listener
    if ($listener.ExecutablePath -ine $wkPython) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.ParentProcessId)"
    }
    if (-not $owner -or $owner.ExecutablePath -ine $wkPython -or $owner.CommandLine -notmatch $expected) {
        throw 'No se pudo verificar que el servidor pertenece a esta copia de Wiener Kingdom.'
    }
    return $listener
}

function Test-WienerKingdomHealth {
    try {
        $health = Invoke-RestMethod -Uri "$wkUrl/salud/" -TimeoutSec 3
        return ($health.status -eq 'ok' -and $health.service -eq 'reino-commerce')
    } catch { return $false }
}
