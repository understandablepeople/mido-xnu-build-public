param(
    [string]$Ndk = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358')
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
$compiler = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android21-clang.cmd'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw "NDK compiler not found: $compiler"
}
$outputDirectory = Join-Path $workspace 'artifacts\fbprobe'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$executable = Join-Path $outputDirectory 'fbprobe'
& $compiler -static -O2 -Wall -Wextra -Werror (Join-Path $PSScriptRoot 'fbprobe.c') -o $executable
if ($LASTEXITCODE -ne 0) {
    throw 'Framebuffer probe compilation failed.'
}
Get-FileHash -LiteralPath $executable -Algorithm SHA256
