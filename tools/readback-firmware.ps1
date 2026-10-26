param(
    [string]$Adb = 'C:\platform-tools\adb.exe',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\artifacts\firmware-readback')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) { throw "ADB not found: $Adb" }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Output already exists. Choose a new -OutputDirectory.' }
$deviceLines = @(& $Adb devices)
if ($LASTEXITCODE -ne 0) { throw 'ADB device listing failed.' }
$devices = @($deviceLines | Where-Object { $_ -match '^\S+\s+(device|recovery)\s*$' })
if ($devices.Count -ne 1) { throw 'Exactly one connected recovery device is required.' }
$serial = ($devices[0] -split '\s+')[0]
$userId = @(& $Adb -s $serial shell id -u)
if ($LASTEXITCODE -ne 0 -or ($userId -join '').Trim() -ne '0') { throw 'Root ADB is required. Keep the phone in TWRP.' }
$recoveryVersion = @(& $Adb -s $serial shell getprop ro.twrp.version)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($recoveryVersion -join ''))) { throw 'TWRP was not detected.' }
$partitions = [ordered]@{
    'aboot' = 'mmcblk0p19'
    'abootbak' = 'mmcblk0p20'
    'persist' = 'mmcblk0p26'
}
$sources = @()
foreach ($partition in $partitions.GetEnumerator()) {
    $source = '/dev/block/bootdevice/by-name/' + $partition.Key
    $resolvedLines = @(& $Adb -s $serial shell "readlink -f $source")
    if ($LASTEXITCODE -ne 0 -or ($resolvedLines -join '').Trim() -ne ('/dev/block/' + $partition.Value)) {
        throw "Partition mapping differs from the recorded mido layout: $($partition.Key). Nothing was copied."
    }
    $sectorLines = @(& $Adb -s $serial shell "cat /sys/class/block/$($partition.Value)/size")
    $sectorText = ($sectorLines -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or $sectorText -notmatch '^[0-9]{1,9}$') { throw "Cannot read partition size: $($partition.Key)" }
    $bytes = [long]$sectorText * 512
    if ($bytes -le 0 -or $bytes -gt 128MB) { throw "Unexpected partition size: $($partition.Key), $bytes bytes" }
    $sources += [pscustomobject]@{ Name = $partition.Key; Source = $source; Resolved = '/dev/block/' + $partition.Value; Bytes = $bytes }
}
$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination | Out-Null
$session = [guid]::NewGuid().ToString('N')
$manifest = @()
foreach ($partition in $sources) {
    $remote = '/tmp/mido-readback-' + $session + '-' + $partition.Name + '.img'
    $local = Join-Path $destination ($partition.Name + '.img')
    & $Adb -s $serial shell "dd if=$($partition.Source) of=$remote bs=1048576"
    if ($LASTEXITCODE -ne 0) { throw "Readback to recovery RAM failed: $($partition.Name)" }
    $hashLines = @(& $Adb -s $serial shell "sha256sum $remote")
    if ($LASTEXITCODE -ne 0) { throw "Recovery checksum failed: $($partition.Name)" }
    $remoteHash = (($hashLines -join ' ').Trim() -split '\s+')[0]
    if ($remoteHash -notmatch '^[a-fA-F0-9]{64}$') { throw "Invalid checksum output: $($partition.Name)" }
    & $Adb -s $serial pull $remote $local
    if ($LASTEXITCODE -ne 0) { throw "Host transfer failed: $($partition.Name)" }
    if ((Get-Item -LiteralPath $local).Length -ne $partition.Bytes) { throw "Size mismatch: $($partition.Name)" }
    $hostHash = (Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash
    if ($hostHash -ne $remoteHash) { throw "Checksum mismatch: $($partition.Name)" }
    $manifest += [pscustomobject]@{ Name = $partition.Name; Source = $partition.Source; Resolved = $partition.Resolved; Bytes = $partition.Bytes; SHA256 = $hostHash }
    Write-Output "$($partition.Name): verified, $($partition.Bytes) bytes"
}
$manifest | ConvertTo-Json -Depth 3 | Out-File -LiteralPath (Join-Path $destination 'manifest.json') -Encoding utf8
Write-Output "Verified copies saved to $destination"
Write-Output 'Source partitions were read only. Temporary copies remain in recovery /tmp (RAM) until reboot. Never flash these files as an experiment.'
