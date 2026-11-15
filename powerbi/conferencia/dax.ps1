# Roda uma consulta DAX no Power BI Desktop aberto e grava o resultado em JSON (UTF-8).
# Uso: powershell -File powerbi\conferencia\dax.ps1 -DaxArquivo consulta.dax -Saida resultado.json [-Porta 12345]
# Chamado por conferir.py; a porta sai do workspace mais recente, como em tools\testar_medidas.ps1.
param([Parameter(Mandatory)][string]$DaxArquivo, [Parameter(Mandatory)][string]$Saida, [int]$Porta = 0)
$ErrorActionPreference = "Stop"

$pbi = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
Add-Type -Path "$pbi\bin\Microsoft.PowerBI.AdomdClient.dll"

if ($Porta -eq 0) {
    $ws = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces" -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $arq = if ($ws) { Join-Path $ws.FullName "Data\msmdsrv.port.txt" }
    if ($arq -and (Test-Path $arq)) { $Porta = [int]((Get-Content $arq -Encoding Unicode) -join '') }
    else {
        $proc = Get-Process msmdsrv | Sort-Object StartTime -Descending | Select-Object -First 1
        $Porta = (Get-NetTCPConnection -OwningProcess $proc.Id -State Listen | Select-Object -First 1).LocalPort
    }
}

$dax = [IO.File]::ReadAllText($DaxArquivo, [Text.Encoding]::UTF8)
$con = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Porta")
$con.Open()
try {
    $cmd = $con.CreateCommand(); $cmd.CommandText = $dax
    $r = $cmd.ExecuteReader(); $linhas = New-Object System.Collections.ArrayList
    while ($r.Read()) {
        $o = [ordered]@{}
        for ($i = 0; $i -lt $r.FieldCount; $i++) {
            $v = $r.GetValue($i)
            # Numero vai como texto invariante (R = ida e volta sem perder casas); vazio vira null
            if ($v -is [double] -or $v -is [decimal] -or $v -is [long] -or $v -is [int]) { $v = ([double]$v).ToString("R", [Globalization.CultureInfo]::InvariantCulture) }
            elseif ($v -is [DBNull]) { $v = $null }
            $o[$r.GetName($i)] = $v
        }
        [void]$linhas.Add([pscustomobject]$o)
    }
    $r.Close()
} finally { $con.Close() }
[IO.File]::WriteAllText($Saida, (ConvertTo-Json -InputObject @($linhas) -Depth 3), (New-Object Text.UTF8Encoding $false))
