$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
$collector = Join-Path $workspace 'tools\collect-live.ps1'
$fakeAdb = Join-Path $PSScriptRoot 'fixtures\fake-adb.ps1'
$testDirectory = Join-Path $workspace ('artifacts\collector-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDirectory | Out-Null
$previousMode = $env:COLLECTOR_TEST_MODE
try {
    foreach ($mode in @('unprivileged', 'empty-tree', 'invalid-header', 'valid-header', 'recovery', 'offline', 'unauthorized', 'no-device', 'multiple')) {
        $env:COLLECTOR_TEST_MODE = $mode
        $output = Join-Path $testDirectory $mode
        $failure = $null
        try {
            & $collector -Adb $fakeAdb -OutputDirectory $output | Out-Null
        } catch {
            $failure = $_.Exception.Message
        }
        if ($mode -in @('offline', 'unauthorized', 'no-device', 'multiple')) {
            if ($failure -notlike '*Connect exactly one*ADB reported:*' -or (Test-Path -LiteralPath $output)) {
                throw "Unavailable or ambiguous device list was not rejected: $mode"
            }
        } elseif ($mode -eq 'unprivileged') {
            if ($failure -notlike '*Root ADB is required*' -or (Test-Path -LiteralPath $output)) {
                throw 'Unprivileged ADB was not rejected before output creation.'
            }
        } elseif ($mode -eq 'empty-tree') {
            if ($failure -notlike '*empty device-tree directory*') {
                throw "Empty tree was not rejected: $failure"
            }
        } elseif ($mode -eq 'invalid-header') {
            if ($failure -notlike '*invalid header*') {
                throw "Invalid FDT header was not rejected: $failure"
            }
        } elseif ($failure) {
            throw "Expected mock capture success: $failure"
        }
        Write-Output "PASS: $mode"
    }
} finally {
    $env:COLLECTOR_TEST_MODE = $previousMode
}
