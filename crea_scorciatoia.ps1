$pyw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "Manca .venv: esegui prima l'installazione descritta nel README."
    exit 1
}
$link = Join-Path ([Environment]::GetFolderPath("Desktop")) "DWG-DXF Studio.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$s.TargetPath = $pyw
$s.Arguments = "app.py"
$s.WorkingDirectory = $PSScriptRoot
$s.IconLocation = "$env:SystemRoot\System32\shell32.dll,70"
$s.Save()
Write-Host 'Scorciatoia "DWG-DXF Studio" creata sul desktop.'
