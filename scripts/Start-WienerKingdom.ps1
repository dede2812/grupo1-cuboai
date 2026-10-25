[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WienerKingdom.Local.ps1')

try {
    if (-not (Test-Path -LiteralPath $wkPython -PathType Leaf)) {
        throw 'Falta web\.venv\Scripts\python.exe. Segui la instalacion de docs/11_INSTALACION_Y_DESPLIEGUE.md.'
    }
    $listener = Get-WienerKingdomListener
    if ($listener) {
        if (-not (Test-WienerKingdomHealth)) {
            throw 'El servidor existe pero su comprobacion de salud fallo. Revisa .artifacts/server-error.log.'
        }
        Write-Host 'Wiener Kingdom ya esta funcionando.'
    } else {
        New-Item -ItemType Directory -Force -Path $wkRuntime, $wkArtifacts | Out-Null
        Push-Location -LiteralPath $wkWeb
        try {
            & $wkPython $wkManage check
            if ($LASTEXITCODE -ne 0) { throw 'Django detecto un problema de configuracion.' }
            & $wkPython $wkManage migrate --noinput
            if ($LASTEXITCODE -ne 0) { throw 'No se pudieron aplicar las migraciones.' }
        } finally { Pop-Location }
        $arguments = '"' + $wkManage + '" runserver 127.0.0.1:8000 --noreload'
        $server = Start-Process -FilePath $wkPython -ArgumentList $arguments -WorkingDirectory $wkWeb `
            -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wkArtifacts 'server.log') `
            -RedirectStandardError (Join-Path $wkArtifacts 'server-error.log') -PassThru
        Set-Content -LiteralPath (Join-Path $wkRuntime 'server.pid') -Value $server.Id -Encoding ascii
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if (Test-WienerKingdomHealth) { $ready = $true; break }
            $server.Refresh()
            if ($server.HasExited) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) { throw 'El servidor no inicio. Consulta .artifacts/server-error.log.' }
        $null = Get-WienerKingdomListener
        Write-Host 'Wiener Kingdom esta listo.'
    }
    Write-Host "$wkUrl/s/wiener-kingdom/"
    Write-Host "Panel: $wkUrl/negocio/wiener-kingdom/"
    Write-Host 'Este servidor es local de desarrollo. Mantenelo encendido para abrir los enlaces.'
    if (-not $NoBrowser) { Start-Process "$wkUrl/s/wiener-kingdom/" }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
