# Exporta stop_id, latitude e longitude dos pontos (fato_paradas) do modelo aberto no Desktop
# para powerbi/recursos/pontos.csv. A arte usa o arquivo para desenhar a cidade no fundo do mapa.
# Dado publico do GTFS da PBH; rodar de novo so quando entrar ponto novo.
# Uso: powershell -File powerbi\tools\exportar_pontos.ps1 [-Porta 12345]
param([int]$Porta = 0)
$pbi = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
Add-Type -Path "$pbi\bin\Microsoft.PowerBI.AdomdClient.dll"
if ($Porta -eq 0) {
    $proc = Get-Process msmdsrv -ErrorAction Stop | Sort-Object StartTime -Descending | Select-Object -First 1
    $Porta = (Get-NetTCPConnection -OwningProcess $proc.Id -State Listen | Select-Object -First 1).LocalPort
}
$con = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Porta")
$con.Open()
$cmd = $con.CreateCommand()
$cmd.CommandText = "EVALUATE SUMMARIZECOLUMNS ( fato_paradas[stop_id], ""lat"", MAX ( fato_paradas[stop_lat] ), ""lon"", MAX ( fato_paradas[stop_lon] ) ) ORDER BY fato_paradas[stop_id]"
$r = $cmd.ExecuteReader()
$inv = [Globalization.CultureInfo]::InvariantCulture
$linhas = New-Object System.Collections.Generic.List[string]
$linhas.Add("stop_id,lat,lon")
while ($r.Read()) {
    $linhas.Add(("{0},{1},{2}" -f $r.GetValue(0), ([double]$r.GetValue(1)).ToString("0.00000", $inv), ([double]$r.GetValue(2)).ToString("0.00000", $inv)))
}
$r.Close(); $con.Close()
$saida = Join-Path $PSScriptRoot "..\recursos\pontos.csv"
[IO.File]::WriteAllLines((Resolve-Path (Split-Path $saida)).Path + "\pontos.csv", $linhas)
"{0} pontos em {1}" -f ($linhas.Count - 1), $saida
