# 仅准备本地照片材料；不会创建资源、写 DynamoDB 或上传 S3。
param(
    [Parameter(Mandatory = $true)][string]$OriginalDirectory,
    [string]$SelectionPath,
    [string]$BaselinePath,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$pythonExecutable = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw '未找到 Python，请配置带 Pillow 的 Python 3.12 或更新版本。' }
    $pythonExecutable = $pythonCommand.Source
}
$prepareArguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'prepare_photos.py'), $OriginalDirectory)
if ($SelectionPath) { $prepareArguments += @('--selection', $SelectionPath) }
if ($BaselinePath) { $prepareArguments += @('--baseline', $BaselinePath) }
if ($OutputDirectory) { $prepareArguments += @('--output', $OutputDirectory) }
& $pythonExecutable @prepareArguments
if ($LASTEXITCODE -ne 0) { throw '照片批次未完成；没有调用 AWS。检查报错后使用新的输出目录。' }
