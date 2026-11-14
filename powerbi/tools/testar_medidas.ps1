# Avalia todas as medidas no motor local do Power BI Desktop aberto e lista as que dão erro.
# Uso: powershell -File scripts\testar_medidas.ps1 [-Porta 12345] [-Dax "EVALUATE ..."]
param([int]$Porta = 0, [string]$Dax = "", [string]$DaxArquivo = "")
if ($DaxArquivo) { $Dax = Get-Content $DaxArquivo -Raw -Encoding UTF8 }

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

function Consulta([string]$q) {
    $cmd = $con.CreateCommand(); $cmd.CommandText = $q
    $r = $cmd.ExecuteReader(); $linhas = @()
    while ($r.Read()) { $o = [ordered]@{}; for ($i = 0; $i -lt $r.FieldCount; $i++) { $o[$r.GetName($i)] = $r.GetValue($i) }; $linhas += [pscustomobject]$o }
    $r.Close(); return $linhas
}

if ($Dax) { Consulta $Dax | Format-Table -AutoSize | Out-String -Width 400; $con.Close(); return }

$medidas = Consulta "SELECT [Name] FROM `$SYSTEM.TMSCHEMA_MEASURES"
$erros = 0
foreach ($m in $medidas) {
    $n = $m.Name -replace '\]', ']]'
    try { $v = (Consulta "EVALUATE ROW(""v"", [$n])")[0].'[v]'; if (-not ($m.Name -like 'HTML*')) { "{0,-28} {1}" -f $m.Name, $v } }
    catch { $erros++; "ERRO  {0}: {1}" -f $m.Name, ($_.Exception.InnerException.Message, $_.Exception.Message | Where-Object { $_ } | Select-Object -First 1) }
}
"--- $($medidas.Count) medidas, $erros com erro"
$con.Close()
