#Requires -Version 7.0
# 本地签发邀请，不调用 AWS，不输出私钥，不把邀请链接写进 dist/。
param([ValidateRange(1, 30)][int]$Days = 30)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config/cloudfront-invitation.json') -Raw | ConvertFrom-Json
if ($config.distributionDomain -notmatch '^[a-z0-9]+\.cloudfront\.net$' -or
    $config.publicKeyId -notmatch '^[A-Z0-9]+$' -or
    $config.entryPath -ne '/invite/index.html') {
    throw '邀请配置无效，请核对域名、公钥 ID 和入口路径。'
}
$keyDirectory = Join-Path $projectRoot '.local/cloudfront'
$privatePath = Join-Path $keyDirectory 'private-key.pem'
$publicPath = Join-Path $keyDirectory 'public-key.pem'
if (-not (Test-Path -LiteralPath $privatePath) -or -not (Test-Path -LiteralPath $publicPath)) {
    throw '找不到本地密钥；先恢复对应密钥，不要为已有公钥 ID 随意换一套新私钥。'
}

function ConvertTo-CloudFrontBase64([byte[]]$Bytes) {
    return [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('=', '_').Replace('/', '~')
}

$createdAt = [DateTimeOffset]::UtcNow
$expiresAt = $createdAt.AddDays($Days)
$origin = 'https://' + $config.distributionDomain
$policy = [ordered]@{
    Statement = @(@{
        Resource = $origin + '/*'
        Condition = @{ DateLessThan = @{ 'AWS:EpochTime' = $expiresAt.ToUnixTimeSeconds() } }
    })
} | ConvertTo-Json -Depth 8 -Compress
$policyBytes = [Text.Encoding]::UTF8.GetBytes($policy)
$signer = [Security.Cryptography.RSA]::Create()
$verifier = [Security.Cryptography.RSA]::Create()
try {
    $signer.ImportFromPem([IO.File]::ReadAllText($privatePath))
    $verifier.ImportFromPem([IO.File]::ReadAllText($publicPath))
    if ($signer.KeySize -ne 2048) { throw '本工具当前要求 RSA 2048 密钥。' }
    $signature = $signer.SignData($policyBytes,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    if (-not $verifier.VerifyData($policyBytes, $signature,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1)) {
        throw '本地公私钥不匹配，未生成邀请文件。'
    }
    # 凭证放在 # 后，浏览器向服务器请求入口文件时不发送该片段。
    $fragment = 'v=1&p=' + (ConvertTo-CloudFrontBase64 $policyBytes) +
        '&s=' + (ConvertTo-CloudFrontBase64 $signature) + '&k=' + $config.publicKeyId
    $link = $origin + $config.entryPath + '#' + $fragment
    $fileName = 'invitation-' + $createdAt.ToString('yyyyMMdd-HHmmss') + '-' +
        [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt'
    $outputPath = Join-Path $keyDirectory $fileName
    $stream = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($link + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
    Write-Output "邀请已保存：$outputPath"
    Write-Output ('到期时间（日本时间）：' + $expiresAt.ToOffset([TimeSpan]::FromHours(9)).ToString('yyyy-MM-dd HH:mm:ss zzz'))
    Write-Output '文件中的完整链接可转发；到期时间不会因转发或重新打开而延长。'
} finally {
    $verifier.Dispose()
    $signer.Dispose()
}
