param(
    [Parameter(Mandatory)][string]$Installer,
    [switch]$RequireCleanImage
)
$ErrorActionPreference = 'Stop'
$msi = (Resolve-Path -LiteralPath $Installer).Path
if ($RequireCleanImage -and (Get-Command python, python3, py -ErrorAction SilentlyContinue)) {
    throw 'The test image already contains a Python command.'
}
$target = Join-Path $env:LOCALAPPDATA 'Programs\VRC Transf'
$exe = Join-Path $target 'VRC Transf.exe'
if (Test-Path -LiteralPath $target) { throw "Test requires an unused install directory: $target" }
$work = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ('vrc-install-test-' + [guid]::NewGuid()))

function Invoke-Msi([string]$operation) {
    $log = Join-Path $work.FullName ($operation + '.log')
    $process = Start-Process msiexec.exe -ArgumentList "/$operation `"$msi`" /qn /norestart /L*v `"$log`"" -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        Get-Content -LiteralPath $log -Tail 80
        throw "Windows Installer /$operation exited with $($process.ExitCode)"
    }
}

Invoke-Msi 'i'
try {
    foreach ($file in 'VRC Transf.exe', 'python313.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll') {
        if (!(Test-Path -LiteralPath (Join-Path $target $file))) { throw "Missing installed file: $file" }
    }
    $shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'VRC Transf.lnk'
    if (!(Test-Path -LiteralPath $shortcut)) { throw 'Missing Start menu entry' }
    $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
    foreach ($name in 'PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY', 'DASHSCOPE_API_KEY', 'DASHSCOPE_WORKSPACE_ID') {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $report = Join-Path $work.FullName 'smoke.txt'
    $app = Start-Process -FilePath $exe -ArgumentList "--self-test `"$report`"" -WorkingDirectory $work.FullName -PassThru -WindowStyle Hidden
    if (!$app.WaitForExit(60000)) { $app.Kill(); $app.WaitForExit(); throw 'Installed application timed out' }
    $result = if (Test-Path -LiteralPath $report) { Get-Content -Raw -LiteralPath $report } else { 'No report produced' }
    if ($app.ExitCode -ne 0 -or $result -ne 'PASS') { throw "Application exited with $($app.ExitCode): $result" }
    Write-Output 'PASS: installed GUI, two demo captions, mini window, audio libraries, resampling and TLS.'
} finally {
    Invoke-Msi 'x'
}
if ((Test-Path -LiteralPath $exe) -or (Test-Path -LiteralPath $shortcut)) { throw 'Uninstall left application or shortcut behind' }
Write-Output 'PASS: uninstall removed the application and Start menu entry.'
