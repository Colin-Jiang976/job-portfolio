#Requires -Version 7.0
# 仅向当前网站发出 HEAD 请求；不修改 AWS，不输出私钥或访问凭证。
param([ValidateRange(3, 20)][int]$TimeoutSeconds = 10)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config/cloudfront-invitation.json') -Raw | ConvertFrom-Json
if ($config.distributionDomain -notmatch '^[a-z0-9]+\.cloudfront\.net$') { throw '域名配置无效。' }
$origin = 'https://' + $config.distributionDomain
$keyDirectory = Join-Path $projectRoot '.local/cloudfront'
$rsa = [Security.Cryptography.RSA]::Create()
$rsa.ImportFromPem([IO.File]::ReadAllText((Join-Path $keyDirectory 'private-key.pem')))

function ConvertTo-CfBase64([byte[]]$Bytes) {
    [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('=', '_').Replace('/', '~')
}
function Get-Policy([long]$Expiry) {
    [ordered]@{ Statement = @(@{
        Resource = $origin + '/*'
        Condition = @{ DateLessThan = @{ 'AWS:EpochTime' = $Expiry } }
    }) } | ConvertTo-Json -Compress -Depth 8
}
function Get-Cookie([string]$Policy, [byte[]]$Signature) {
    'CloudFront-Policy=' + (ConvertTo-CfBase64 ([Text.Encoding]::UTF8.GetBytes($Policy))) +
        '; CloudFront-Signature=' + (ConvertTo-CfBase64 $Signature) +
        '; CloudFront-Key-Pair-Id=' + $config.publicKeyId + '; CloudFront-Hash-Algorithm=SHA256'
}
function Get-Signature([string]$Policy) {
    # 禁止 PowerShell 将 byte[] 展开成多个函数返回值。
    ,$rsa.SignData([Text.Encoding]::UTF8.GetBytes($Policy),
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1)
}
function Invoke-Head([string]$RequestPath, [string]$Cookie) {
    # 每项使用新客户端，避免先前的有效 Cookie 污染无凭证或错误凭证测试。
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Head, $origin + $RequestPath)
    try {
        if ($Cookie) { $request.Headers.TryAddWithoutValidation('Cookie', $Cookie) | Out-Null }
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        try { return [int]$response.StatusCode } finally { $response.Dispose() }
    } finally { $request.Dispose(); $client.Dispose() }
}

try {
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $validPolicy = Get-Policy ($now + 300)
    $validSignature = Get-Signature $validPolicy
    $validCookie = Get-Cookie $validPolicy $validSignature
    $tamperedCookie = Get-Cookie (Get-Policy ($now + 3600)) $validSignature
    $expiredPolicy = Get-Policy ($now - 60)
    $expiredCookie = Get-Cookie $expiredPolicy (Get-Signature $expiredPolicy)
    $cases = @(
        @{ Name = '公开邀请入口'; Path = '/invite/index.html'; Cookie = ''; Expected = 200 },
        @{ Name = '无凭证首页'; Path = '/'; Cookie = ''; Expected = 403 },
        @{ Name = '无凭证照片'; Path = '/assets/photos/IMG_8655.webp'; Cookie = ''; Expected = 403 },
        @{ Name = '有效凭证首页'; Path = '/'; Cookie = $validCookie; Expected = 200 },
        @{ Name = '有效凭证照片'; Path = '/assets/photos/IMG_8655.webp'; Cookie = $validCookie; Expected = 200 },
        @{ Name = '同一凭证在另一新客户端'; Path = '/index.html'; Cookie = $validCookie; Expected = 200 },
        @{ Name = '篡改到期时间但沿用旧签名'; Path = '/index.html'; Cookie = $tamperedCookie; Expected = 403 },
        @{ Name = '签名正确但已经过期'; Path = '/index.html'; Cookie = $expiredCookie; Expected = 403 }
    )
    $failed = $false
    foreach ($case in $cases) {
        try { $actual = Invoke-Head $case.Path $case.Cookie }
        catch {
            Write-Output ('UNVERIFIED ' + $case.Name + '：未取得 HTTP 响应，不能据此判断 AWS 状态。')
            Write-Output $_.Exception.Message
            exit 2
        }
        $passed = $actual -eq $case.Expected
        if (-not $passed) { $failed = $true }
        $label = if ($passed) { 'PASS' } else { 'FAIL' }
        Write-Output ($label + ' ' + $case.Name + '：HTTP ' + $actual + '，预期 ' + $case.Expected)
    }
    if ($failed) { exit 1 }
} finally { $rsa.Dispose() }
