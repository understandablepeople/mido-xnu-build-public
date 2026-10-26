param(
    [string]$Adb = 'C:\platform-tools\adb.exe',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\artifacts\live-data')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) {
    throw "ADB not found: $Adb"
}
if (Test-Path -LiteralPath $OutputDirectory) {
    throw 'Output already exists. Choose a new -OutputDirectory to preserve the previous capture.'
}
$deviceLines = @(& $Adb devices)
if ($LASTEXITCODE -ne 0) {
    throw 'ADB could not list devices.'
}
$devices = @($deviceLines | Where-Object { $_ -match '^\S+\s+(device|recovery)\s*$' })
if ($devices.Count -ne 1) {
    throw ('Connect exactly one authorized Android or recovery device. ADB reported:' + [Environment]::NewLine + ($deviceLines -join [Environment]::NewLine))
}
$serial = ($devices[0] -split '\s+')[0]
$userId = @(& $Adb -s $serial shell id -u)
if ($LASTEXITCODE -ne 0 -or ($userId -join '').Trim() -ne '0') {
    throw 'Root ADB is required for this hardware capture. Boot the installed TWRP manually and retry. This script does not request root or reboot the phone.'
}
$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination | Out-Null
$nativePreferenceExists = Test-Path variable:PSNativeCommandUseErrorActionPreference
if ($nativePreferenceExists) {
    $savedNativePreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
}
try {
    $captures = [ordered]@{
        'kernel.txt' = 'uname -a'
        'memory.txt' = 'cat /proc/meminfo; cat /proc/iomem'
        'input.txt' = 'cat /proc/bus/input/devices'
        'display.txt' = 'for f in /sys/class/graphics/fb0/name /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/stride /sys/class/graphics/fb0/bits_per_pixel /sys/class/graphics/fb0/msm_fb_panel_info; do echo "--- $f"; if [ -r "$f" ]; then cat "$f"; else echo unavailable; fi; done'
        'tree-paths.txt' = 'ls -ld /sys/firmware/fdt /sys/firmware/devicetree/base /proc/device-tree'
        'environment.txt' = 'id; getprop ro.bootmode; getprop ro.twrp.version'
        'cmdline.txt' = 'cat /proc/cmdline'
        'dmesg.txt' = 'dmesg'
    }
    foreach ($capture in $captures.GetEnumerator()) {
        $captureFile = Join-Path $destination $capture.Key
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $lines = @(& $Adb -s $serial shell $capture.Value 2>&1)
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedPreference
        }
        $lines | Out-File -LiteralPath $captureFile -Encoding utf8
        Write-Output "$($capture.Key): exit $exitCode"
    }
    & $Adb -s $serial shell 'test -r /sys/firmware/fdt'
    if ($LASTEXITCODE -eq 0) {
        & $Adb -s $serial pull /sys/firmware/fdt (Join-Path $destination 'live.dtb')
        if ($LASTEXITCODE -ne 0) {
            throw 'Live FDT transfer failed. Keep the logs and report the error.'
        }
        $treeBytes = [System.IO.File]::ReadAllBytes((Join-Path $destination 'live.dtb'))
        if ($treeBytes.Length -lt 40 -or [System.BitConverter]::ToString($treeBytes, 0, 4) -ne 'D0-0D-FE-ED') {
            throw 'Transferred FDT is empty or has an invalid header. Keep the logs and report the error.'
        }
    } else {
        & $Adb -s $serial shell 'test -d /sys/firmware/devicetree/base'
        if ($LASTEXITCODE -eq 0) {
            & $Adb -s $serial pull /sys/firmware/devicetree/base (Join-Path $destination 'device-tree')
            if ($LASTEXITCODE -ne 0) {
                throw 'Live device-tree transfer failed. Keep the logs and report the error.'
            }
            $treeFiles = @(Get-ChildItem -LiteralPath (Join-Path $destination 'device-tree') -Recurse -File)
            if ($treeFiles.Count -eq 0) {
                throw 'ADB returned an empty device-tree directory. Capture is incomplete; keep the logs.'
            }
        } else {
            throw 'Live tree unavailable. Capture is incomplete. No firmware or storage changes were attempted.'
        }
    }
} finally {
    if ($nativePreferenceExists) {
        $PSNativeCommandUseErrorActionPreference = $savedNativePreference
    }
}
Write-Output "Capture saved to $destination"
Write-Output 'Host files only. No reboot, flash, remount, wipe or device-side file writes were requested.'
