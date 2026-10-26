param(
    [string]$Adb = 'C:\platform-tools\adb.exe',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\artifacts\fbprobe-run')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) {
    throw "ADB not found: $Adb"
}
if (Test-Path -LiteralPath $OutputDirectory) {
    throw 'Output already exists. Choose a new -OutputDirectory.'
}
$deviceLines = @(& $Adb devices)
if ($LASTEXITCODE -ne 0) { throw 'ADB device listing failed.' }
$devices = @($deviceLines | Where-Object { $_ -match '^\S+\s+(device|recovery)\s*$' })
if ($devices.Count -ne 1) { throw 'Exactly one connected recovery device is required.' }
$serial = ($devices[0] -split '\s+')[0]
$userId = @(& $Adb -s $serial shell id -u)
if ($LASTEXITCODE -ne 0 -or ($userId -join '').Trim() -ne '0') {
    throw 'Keep the phone in TWRP with root ADB. This script will not request root.'
}
$recoveryVersion = @(& $Adb -s $serial shell getprop ro.twrp.version)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($recoveryVersion -join ''))) {
    throw 'TWRP was not detected. No executable has been copied to the phone.'
}
& (Join-Path $PSScriptRoot 'build-fbprobe.ps1')
$workspace = Split-Path $PSScriptRoot -Parent
$executable = Join-Path $workspace 'artifacts\fbprobe\fbprobe'
& $Adb -s $serial push $executable /tmp/mido-fbprobe
if ($LASTEXITCODE -ne 0) { throw 'Copy to recovery RAM failed.' }
& $Adb -s $serial shell chmod 500 /tmp/mido-fbprobe
if ($LASTEXITCODE -ne 0) { throw 'Could not mark the temporary RAM executable runnable.' }
$probeOutput = @(& $Adb -s $serial shell /tmp/mido-fbprobe)
if ($LASTEXITCODE -ne 0) { throw 'Framebuffer query failed. No video-mode changes were requested.' }
$probeJson = $probeOutput -join [Environment]::NewLine
$parsed = $probeJson | ConvertFrom-Json
if ($null -eq $parsed.line_length -or $null -eq $parsed.smem_start) {
    throw 'Probe output was incomplete.'
}
$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination | Out-Null
$probeJson | Out-File -LiteralPath (Join-Path $destination 'fbprobe.json') -Encoding utf8
Write-Output $probeJson
Write-Output "Saved to $destination"
Write-Output 'The executable remains in recovery /tmp (RAM) until reboot. No partition or framebuffer writes were requested.'
