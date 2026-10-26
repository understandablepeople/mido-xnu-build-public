param(
    [string]$Ndk = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358'),
    [string]$OutputDirectory = '',
    [switch]$Diagnostics
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
$source = Join-Path $workspace 'devices\mido\screen-test'
if (-not $OutputDirectory) {
    $defaultName = if ($Diagnostics) { 'arm64-diagnostics-build-v1' } else { 'arm64-screen-build-v2' }
    $OutputDirectory = Join-Path $workspace (Join-Path 'artifacts' $defaultName)
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
$artifactRoot = [IO.Path]::GetFullPath((Join-Path $workspace 'artifacts')) + [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must be a new subdirectory of workspace artifacts.'
}
if (Test-Path -LiteralPath $output) {
    throw 'Output already exists. Choose another -OutputDirectory; nothing was overwritten.'
}
$bin = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin'
$compiler = Join-Path $bin 'clang.exe'
$linker = Join-Path $bin 'ld.lld.exe'
$objcopy = Join-Path $bin 'llvm-objcopy.exe'
$readelf = Join-Path $bin 'llvm-readelf.exe'
$objdump = Join-Path $bin 'llvm-objdump.exe'
foreach ($tool in @($compiler, $linker, $objcopy, $readelf, $objdump)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Missing NDK tool: $tool"
    }
}
Get-Command python -ErrorAction Stop | Out-Null
$reference = Join-Path $workspace 'artifacts\recovery-analysis\dtb-00.dtb'
if ((Get-FileHash -LiteralPath $reference -Algorithm SHA256).Hash -ne 'D595C03A0FC5A55B78451B0D761A357682FB5CF86AC7629B52D9977B6551B420') {
    throw 'Original recovery DTB checksum mismatch.'
}
New-Item -ItemType Directory -Path $output | Out-Null
& $compiler --version | Out-File -LiteralPath (Join-Path $output 'compiler.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Compiler version query failed.' }
$common = @('--target=aarch64-none-elf', '-march=armv8-a', '-mgeneral-regs-only', '-mstrict-align', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-fpie', '-fvisibility=hidden', '-O2', '-Wall', '-Wextra', '-Werror')
$entrySource = Join-Path $source 'entry.S'
if ($Diagnostics) {
    $entrySource = Join-Path $workspace 'devices\mido\diagnostics\entry.S'
    $common += @('-DMIDO_DIAGNOSTICS=1', '-ffixed-x28')
}
& $compiler --target=aarch64-none-elf -march=armv8-a -c $entrySource -o (Join-Path $output 'entry.o')
if ($LASTEXITCODE -ne 0) { throw 'ARM64 entry assembly failed.' }
& $compiler @common -std=c11 -c (Join-Path $source 'screen.c') -o (Join-Path $output 'screen.o')
if ($LASTEXITCODE -ne 0) { throw 'ARM64 screen compilation failed.' }
$elf = Join-Path $output 'screen.elf'
$objects = @((Join-Path $output 'entry.o'), (Join-Path $output 'screen.o'))
if ($Diagnostics) {
    $diagnosticsSource = Join-Path $workspace 'devices\mido\diagnostics\diagnostics.c'
    $diagnosticsObject = Join-Path $output 'diagnostics.o'
    & $compiler @common -std=c11 -c $diagnosticsSource -o $diagnosticsObject
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostics compilation failed.' }
    $objects += $diagnosticsObject
}
& $linker -static --no-undefined --build-id=none -T (Join-Path $source 'link.ld') @objects -o $elf
if ($LASTEXITCODE -ne 0) { throw 'ARM64 linking failed.' }
& $readelf --all $elf | Out-File -LiteralPath (Join-Path $output 'elf.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'ELF inspection failed.' }
& $objdump -d $elf | Out-File -LiteralPath (Join-Path $output 'disassembly.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Disassembly failed.' }
$payload = Join-Path $output 'screen.bin'
& $objcopy -O binary $elf $payload
if ($LASTEXITCODE -ne 0) { throw 'Binary extraction failed.' }
$packageArguments = @((Join-Path $PSScriptRoot 'pack_screen_test.py'), $payload, $reference, (Join-Path $output 'package'))
if ($Diagnostics) { $packageArguments += '--diagnostics' }
& python @packageArguments
if ($LASTEXITCODE -ne 0) { throw 'Boot image validation or packaging failed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $output 'package\mido-arm64-screen-test.img')
Write-Host 'Host build only. No ADB, fastboot, reboot, flash, erase or device access.'
Write-Host 'STOP: send the build output for review before attempting to boot this image.'
