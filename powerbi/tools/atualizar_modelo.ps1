# Atualiza (refresh full) o modelo aberto no Power BI Desktop pelo motor local, sem usar a interface.
# Os dados só ficam gravados no arquivo quando o relatório for salvo no Desktop.
# Uso: powershell -File scripts\atualizar_modelo.ps1 [-Porta 12345]
param([int]$Porta = 0)
$pbi = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
Add-Type -Path "$pbi\bin\Microsoft.PowerBI.AdomdClient.dll"
if ($Porta -eq 0) {
    $ws = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces" -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $arq = if ($ws) { Join-Path $ws.FullName "Data\msmdsrv.port.txt" }
    if ($arq -and (Test-Path $arq)) { $Porta = [int]((Get-Content $arq -Encoding Unicode) -join '') }
    else {  # sem arquivo de porta: porta em escuta do msmdsrv mais recente
        $proc = Get-Process msmdsrv -ErrorAction Stop | Sort-Object StartTime -Descending | Select-Object -First 1
        $Porta = (Get-NetTCPConnection -OwningProcess $proc.Id -State Listen | Select-Object -First 1).LocalPort
    }
}
$con = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Porta")
$con.Open()
$cmd = $con.CreateCommand(); $cmd.CommandText = "SELECT [CATALOG_NAME] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
$r = $cmd.ExecuteReader(); $r.Read() | Out-Null; $db = $r.GetString(0); $r.Close()
$t0 = Get-Date
$cmd = $con.CreateCommand()
$cmd.CommandText = "{ ""refresh"": { ""type"": ""full"", ""objects"": [ { ""database"": ""$db"" } ] } }"
$cmd.CommandTimeout = 1800
[void]$cmd.ExecuteNonQuery()
"Atualizado em {0:n0} s (porta {1}, banco {2})" -f ((Get-Date) - $t0).TotalSeconds, $Porta, $db
$con.Close()
