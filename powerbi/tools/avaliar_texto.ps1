# Avalia uma consulta DAX que devolve um valor de texto no modelo aberto no Desktop e grava o valor num arquivo.
# Uso: powershell -File powerbi\tools\avaliar_texto.ps1 -DaxArquivo consulta.dax -Saida valor.html [-Porta 12345]
param([Parameter(Mandatory)][string]$DaxArquivo, [Parameter(Mandatory)][string]$Saida, [int]$Porta = 0)
$pbi = (Get-AppxPackage -Name "*PowerBIDesktop*").InstallLocation
Add-Type -Path "$pbi\bin\Microsoft.PowerBI.AdomdClient.dll"
if ($Porta -eq 0) {
    $proc = Get-Process msmdsrv -ErrorAction Stop | Sort-Object StartTime -Descending | Select-Object -First 1
    $Porta = (Get-NetTCPConnection -OwningProcess $proc.Id -State Listen | Select-Object -First 1).LocalPort
}
$con = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Porta")
$con.Open()
$cmd = $con.CreateCommand()
$cmd.CommandText = [IO.File]::ReadAllText($DaxArquivo, [Text.Encoding]::UTF8)
$r = $cmd.ExecuteReader()
$valor = if ($r.Read()) { [string]$r.GetValue(0) } else { "" }
$r.Close(); $con.Close()
[IO.File]::WriteAllText($Saida, $valor, (New-Object Text.UTF8Encoding($false)))
