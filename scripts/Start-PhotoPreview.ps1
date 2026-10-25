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
$pythonExecutable = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw '未找到 Python，请安装 Python 3.12 或配置 Python 运行时。' }
    $pythonExecutable = $pythonCommand.Source
}
& $nodeExecutable (Join-Path $PSScriptRoot 'prepare-photo-data.cjs') $OriginalDirectory
if ($LASTEXITCODE -ne 0) { throw '照片资料准备失败，预览没有启动。' }
& $pythonExecutable -X utf8 (Join-Path $PSScriptRoot 'photo_dev_server.py') --port $Port
