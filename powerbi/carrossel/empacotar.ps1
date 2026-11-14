# Empacota o carrossel e copia para powerbi/recursos, de onde o gerar_pbip.py desempacota no relatorio.
# Uso (na raiz do repositorio): powershell -File powerbi/carrossel/empacotar.ps1
$ErrorActionPreference = "Stop"
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $aqui
try {
    if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund }
    npx pbiviz package
    $guid = (Get-Content pbiviz.json -Raw | ConvertFrom-Json).visual.guid
    $pacote = Get-ChildItem dist -Filter "$guid.*.pbiviz" | Sort-Object LastWriteTime | Select-Object -Last 1
    Copy-Item $pacote.FullName (Join-Path $aqui "..\recursos\$guid.pbiviz") -Force
    Write-Output "copiado: recursos\$guid.pbiviz"
} finally { Pop-Location }
