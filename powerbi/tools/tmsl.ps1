# Executa um comando TMSL (JSON) no modelo aberto no Desktop. "DB" no arquivo vira o nome do banco.
# Ex.: alterar particao, refresh "calculate", createOrReplace de medida (tools/aplicar_html.py).
# Uso: powershell -File powerbi\tools\tmsl.ps1 -Arquivo comando.json
param([string]$Arquivo)
$pbi = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
Add-Type -Path "$pbi\bin\Microsoft.PowerBI.AdomdClient.dll"
$ws = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$Porta = [int]((Get-Content (Join-Path $ws.FullName "Data\msmdsrv.port.txt") -Encoding Unicode) -join '')
$con = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Porta"); $con.Open()
$cmd = $con.CreateCommand(); $cmd.CommandText = "SELECT [CATALOG_NAME] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
$r = $cmd.ExecuteReader(); $r.Read() | Out-Null; $db = $r.GetString(0); $r.Close()
$t = (Get-Content $Arquivo -Raw -Encoding UTF8) -replace '"DB"', """$db"""
$cmd = $con.CreateCommand(); $cmd.CommandText = $t; $cmd.CommandTimeout = 1800
$t0 = Get-Date; [void]$cmd.ExecuteNonQuery()
"TMSL ok em {0:n0} s" -f ((Get-Date) - $t0).TotalSeconds
$con.Close()
