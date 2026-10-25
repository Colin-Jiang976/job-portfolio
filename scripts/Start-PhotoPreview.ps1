# 本地预览：只读取已选择的 JPG，不连接 AWS。
param(
    [Parameter(Mandatory = $true)][string]$OriginalDirectory,
    [ValidateRange(1024, 65535)][int]$Port = 8766
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$nodeExecutable = if ($nodeCommand) { $nodeCommand.Source } else {
    Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
}
if (-not (Test-Path -LiteralPath $nodeExecutable)) { throw '未找到 Node.js，请安装官方 Node.js 24 或在已配置的终端运行。' }
& $nodeExecutable (Join-Path $PSScriptRoot 'prepare-photo-data.cjs') $OriginalDirectory
if ($LASTEXITCODE -ne 0) { throw '照片资料准备失败，预览没有启动。' }
$previousPort = $env:PHOTO_PREVIEW_PORT
try {
    $env:PHOTO_PREVIEW_PORT = [string]$Port
    & $nodeExecutable (Join-Path $PSScriptRoot 'photo-dev-server.mjs')
} finally { $env:PHOTO_PREVIEW_PORT = $previousPort }
