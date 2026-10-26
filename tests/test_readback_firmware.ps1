$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
$script = Join-Path $workspace 'tools\readback-firmware.ps1'
$fakeAdb = Join-Path $PSScriptRoot 'fixtures\readback-adb.ps1'
$testDirectory = Join-Path $workspace ('artifacts\readback-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDirectory | Out-Null
$previousMode = $env:READBACK_TEST_MODE
try {
    $expectations = [ordered]@{
        'success' = $null
        'wrong-mapping' = '*Partition mapping differs*'
        'oversize' = '*Unexpected partition size*'
        'unprivileged' = '*Root ADB is required*'
        'no-twrp' = '*TWRP was not detected*'
        'short-copy' = '*Size mismatch*'
        'hash-mismatch' = '*Checksum mismatch*'
    }
    foreach ($entry in $expectations.GetEnumerator()) {
        $env:READBACK_TEST_MODE = $entry.Key
        $global:ReadbackCalls = New-Object 'System.Collections.Generic.List[string]'
        $global:ReadbackRemote = @{}
        $output = Join-Path $testDirectory $entry.Key
        $failure = $null
        try { & $script -Adb $fakeAdb -OutputDirectory $output | Out-Null }
        catch { $failure = $_.Exception.Message }
        if ($entry.Key -eq 'success') {
            if ($failure) { throw "Readback mock unexpectedly failed: $failure" }
            $manifest = Get-Content -LiteralPath (Join-Path $output 'manifest.json') -Raw | ConvertFrom-Json
            if ($manifest.Count -ne 3) { throw 'Missing verified manifest entries.' }
        } elseif ($failure -notlike $entry.Value) {
            throw "Unexpected result for $($entry.Key): $failure"
        }
        if ($entry.Key -in @('wrong-mapping', 'oversize', 'unprivileged', 'no-twrp')) {
            if ((Test-Path -LiteralPath $output) -or @($global:ReadbackCalls | Where-Object { $_ -match 'shell dd ' }).Count) {
                throw 'Preflight failure did not prevent copying.'
            }
        }
        foreach ($call in $global:ReadbackCalls) {
            if ($call -match 'shell dd ' -and $call -notmatch ' of=/tmp/mido-readback-') { throw 'Unsafe mock dd destination.' }
            if ($call -match 'fastboot|reboot|remount|format|wipe') { throw 'Unexpected mutating operation.' }
        }
        Write-Output "PASS: $($entry.Key)"
    }
} finally {
    $env:READBACK_TEST_MODE = $previousMode
    Remove-Variable ReadbackCalls,ReadbackRemote -Scope Global -ErrorAction SilentlyContinue
}
