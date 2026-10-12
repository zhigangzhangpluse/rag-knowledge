# Install the authorized runtime on D: without automatically restarting Windows.
$ErrorActionPreference = 'Stop'
$runtimeRoot = 'D:\RAGRuntime'
$installerPath = Join-Path $runtimeRoot 'downloads\DockerDesktopInstaller.exe'
$logRoot = Join-Path $runtimeRoot 'logs'
$statusPath = Join-Path $logRoot 'installation-status.json'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script as Administrator.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker Inc') {
    throw 'The installer must have a valid Docker signature.'
}
New-Item -ItemType Directory -Force $logRoot,(Join-Path $runtimeRoot 'tmp') | Out-Null
$env:TEMP = Join-Path $runtimeRoot 'tmp'
$env:TMP = $env:TEMP
$state = [ordered]@{ stage='wsl'; pid=$PID; wsl_exit=$null; docker_exit=$null; error=$null }
$state | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
try {
    $wslProcess = Start-Process -FilePath wsl.exe -ArgumentList '--install','--no-distribution','--web-download' -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $logRoot 'wsl-output.log') -RedirectStandardError (Join-Path $logRoot 'wsl-error.log')
    $state.wsl_exit = $wslProcess.ExitCode
    $state.stage = 'docker'
    $state | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    $dockerArgs = @('install','--quiet','--backend=wsl-2','--no-windows-containers',"--installation-dir=$runtimeRoot\Docker","--wsl-default-data-root=$runtimeRoot\docker-data")
    $dockerProcess = Start-Process -FilePath $installerPath -ArgumentList $dockerArgs -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $logRoot 'docker-output.log') -RedirectStandardError (Join-Path $logRoot 'docker-error.log')
    $state.docker_exit = $dockerProcess.ExitCode
    $state.stage = 'finished'
} catch {
    $state.stage = 'failed'
    $state.error = $_.Exception.Message
} finally {
    $state | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}
