$arguments = @($args)
$global:LASTEXITCODE = 0
if ($arguments -contains 'devices') {
    Write-Output "List of devices attached"
    switch ($env:COLLECTOR_TEST_MODE) {
        'recovery' { Write-Output 'test-device recovery' }
        'offline' { Write-Output 'test-device offline' }
        'unauthorized' { Write-Output 'test-device unauthorized' }
        'no-device' { }
        'multiple' { Write-Output 'test-device recovery'; Write-Output 'other-device device' }
        default { Write-Output 'test-device device' }
    }
} elseif (($arguments -contains 'id') -and ($arguments -contains '-u')) {
    if ($env:COLLECTOR_TEST_MODE -eq 'unprivileged') { '2000' } else { '0' }
} elseif ($arguments[-1] -eq 'test -r /sys/firmware/fdt') {
    if ($env:COLLECTOR_TEST_MODE -eq 'empty-tree') { $global:LASTEXITCODE = 1 }
} elseif ($arguments -contains 'pull') {
    $destination = $arguments[-1]
    if ($env:COLLECTOR_TEST_MODE -eq 'empty-tree') {
        New-Item -ItemType Directory -Path $destination | Out-Null
    } else {
        $bytes = New-Object byte[] 40
        if ($env:COLLECTOR_TEST_MODE -in @('valid-header', 'recovery')) {
            $bytes[0] = 0xd0
            $bytes[1] = 0x0d
            $bytes[2] = 0xfe
            $bytes[3] = 0xed
        }
        [System.IO.File]::WriteAllBytes($destination, $bytes)
    }
} else {
    Write-Output 'mock diagnostic output'
}
