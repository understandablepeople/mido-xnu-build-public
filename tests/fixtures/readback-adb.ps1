$arguments = @($args)
$global:LASTEXITCODE = 0
$global:ReadbackCalls.Add(($arguments -join ' '))
if ($arguments -contains 'devices') {
    'List of devices attached'
    'test-device recovery'
} elseif (($arguments -contains 'id') -and ($arguments -contains '-u')) {
    if ($env:READBACK_TEST_MODE -eq 'unprivileged') { '2000' } else { '0' }
} elseif (($arguments -contains 'getprop') -and ($arguments -contains 'ro.twrp.version')) {
    if ($env:READBACK_TEST_MODE -ne 'no-twrp') { '3.7.0_test' }
} elseif ($arguments -contains 'pull') {
    $bytes = $global:ReadbackRemote[$arguments[-2]].Clone()
    if ($env:READBACK_TEST_MODE -eq 'short-copy') { $bytes = $bytes[0..1022] }
    if ($env:READBACK_TEST_MODE -eq 'hash-mismatch') { $bytes[0] = 99 }
    [System.IO.File]::WriteAllBytes($arguments[-1], $bytes)
} else {
    $command = $arguments[-1]
    if ($command -match '^readlink -f /dev/block/bootdevice/by-name/(aboot|abootbak|persist)$') {
        $name = $Matches[1]
        $blocks = @{ aboot = 'mmcblk0p19'; abootbak = 'mmcblk0p20'; persist = 'mmcblk0p26' }
        if ($env:READBACK_TEST_MODE -eq 'wrong-mapping' -and $name -eq 'persist') { '/dev/block/mmcblk0p27' }
        else { '/dev/block/' + $blocks[$name] }
    } elseif ($command -match '^cat /sys/class/block/mmcblk0p(19|20|26)/size$') {
        if ($env:READBACK_TEST_MODE -eq 'oversize') { '999999999' } else { '2' }
    } elseif ($command -match '^dd if=/dev/block/bootdevice/by-name/(aboot|abootbak|persist) of=(/tmp/mido-readback-[a-f0-9]{32}-(aboot|abootbak|persist)\.img) bs=1048576$') {
        if ($Matches[1] -ne $Matches[3]) { throw 'Source/destination name mismatch.' }
        $bytes = New-Object byte[] 1024
        $bytes[0] = 19
        $global:ReadbackRemote[$Matches[2]] = $bytes
    } elseif ($command -match '^sha256sum (/tmp/mido-readback-[a-f0-9]{32}-(aboot|abootbak|persist)\.img)$') {
        $remote = $Matches[1]
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try { $hash = [System.BitConverter]::ToString($hasher.ComputeHash($global:ReadbackRemote[$remote])).Replace('-', '') }
        finally { $hasher.Dispose() }
        "$hash  $remote"
    } else {
        throw "Unexpected mock ADB command: $command"
    }
}
