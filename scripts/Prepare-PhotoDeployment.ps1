# 仅准备本地上传材料；不会创建资源、写 DynamoDB 或上传 S3。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$localRoot = Join-Path $projectRoot '.local/photo-app'
$catalog = Get-Content -LiteralPath (Join-Path $localRoot 'catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$source = Get-Content -LiteralPath (Join-Path $localRoot 'source.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss-fff')
$outputDirectory = Join-Path $localRoot ('deploy-' + $stamp)
New-Item -ItemType Directory -Path $outputDirectory -ErrorAction Stop | Out-Null
$outputPrefix = [IO.Path]::GetFullPath($outputDirectory) + [IO.Path]::DirectorySeparatorChar
foreach ($photo in $catalog) {
    $sourcePath = [IO.Path]::GetFullPath((Join-Path $source.directory $photo.filename))
    $sourcePrefix = [IO.Path]::GetFullPath($source.directory).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $destination = [IO.Path]::GetFullPath((Join-Path $outputDirectory $photo.originalKey))
    if (-not $sourcePath.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $destination.StartsWith($outputPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw '上传路径超出准备目录。' }
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $photo.sha256) { throw '原文件已变化，请重新准备照片资料后再打包。' }
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destination
}
$apiDirectory = Join-Path $projectRoot 'backend/photo-api'
Compress-Archive -LiteralPath (Join-Path $apiDirectory 'lambda_function.py') -DestinationPath (Join-Path $outputDirectory 'photo-api.zip')
$catalogNames = @('catalog.json', 'upload-plan.json')
foreach ($catalogName in $catalogNames) { Copy-Item -LiteralPath (Join-Path $localRoot $catalogName) -Destination (Join-Path $outputDirectory $catalogName) }
# 按本次条数列出确切文件，避免重用旧选择清单残留的批次。
$batchCount = [int][Math]::Ceiling(@($catalog).Count / 25)
for ($batch = 1; $batch -le $batchCount; $batch++) {
    $batchName = 'batch-{0:000}.json' -f $batch
    Copy-Item -LiteralPath (Join-Path $localRoot $batchName) -Destination (Join-Path $outputDirectory $batchName)
}
Write-Output ('已准备本地部署材料：' + $outputDirectory)
Write-Output ('原 JPG 副本 ' + @($catalog).Count + ' 张；Lambda ZIP 1 个；导入批次 ' + $batchCount + ' 个。未调用 AWS。')
