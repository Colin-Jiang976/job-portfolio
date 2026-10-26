#Requires -Version 7.0
# 只读验收现有站点；五张下载副本留在忽略目录，不输出邀请凭证，不修改 AWS。
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$inviteConfig = Get-Content -LiteralPath "$root/config/cloudfront-invitation.json" -Raw | ConvertFrom-Json
$apiConfig = Get-Content -LiteralPath "$root/config/photo-api.json" -Raw | ConvertFrom-Json
$catalog = @(Get-Content -LiteralPath "$root/.local/photo-app/catalog.json" -Raw | ConvertFrom-Json)
$origin = 'https://' + $inviteConfig.distributionDomain
if ($origin -ne 'https://dh0h1qa1vbzc5.cloudfront.net' -or $catalog.Count -ne 5) { throw '本验收仅针对现有站点和五张已选样本。' }
$output = Join-Path $root ('.local/photo-app/verification-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fff'))
[IO.Directory]::CreateDirectory($output) | Out-Null
$rsa = [Security.Cryptography.RSA]::Create()
$handler = [Net.Http.HttpClientHandler]::new()
$handler.UseCookies = $false
$handler.AllowAutoRedirect = $false
$client = [Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(45)
$results = [Collections.Generic.List[object]]::new()

function New-Cookie([long]$Expiry, [switch]$Tamper) {
    $policy = [ordered]@{ Statement = @(@{
        Resource = $origin + '/*'
        Condition = @{ DateLessThan = @{ 'AWS:EpochTime' = $Expiry } }
    }) } | ConvertTo-Json -Depth 8 -Compress
    $signature = $rsa.SignData([Text.Encoding]::UTF8.GetBytes($policy), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    if ($Tamper) { $signature[0] = $signature[0] -bxor 1 }
    $encode = { param([byte[]]$Bytes) [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('=', '_').Replace('/', '~') }
    'CloudFront-Policy=' + (& $encode ([Text.Encoding]::UTF8.GetBytes($policy))) + '; CloudFront-Signature=' + (& $encode $signature) + '; CloudFront-Key-Pair-Id=' + $inviteConfig.publicKeyId + '; CloudFront-Hash-Algorithm=SHA256'
}
function Request([string]$Url, [string]$Cookie = '') {
    $message = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Url)
    try {
        if ($Cookie) { $null = $message.Headers.TryAddWithoutValidation('Cookie', $Cookie) }
        $client.SendAsync($message, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    } finally { $message.Dispose() }
}
function Record([string]$Name, [bool]$Passed, [string]$Detail) {
    $results.Add([pscustomobject]@{ name = $Name; passed = $Passed; detail = $Detail })
    Write-Output ((@('FAIL', 'PASS')[[int]$Passed]) + ' ' + $Name + ' ' + $Detail)
}
try {
    $rsa.ImportFromPem([IO.File]::ReadAllText("$root/.local/cloudfront/private-key.pem"))
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $valid = New-Cookie ($now + 600)
    $expired = New-Cookie ($now - 60)
    $tampered = New-Cookie ($now + 600) -Tamper
    $response = Request ($origin + '/api/photos') $valid
    try {
        if ([int]$response.StatusCode -ne 200) { throw ('获邀 API 返回 HTTP ' + [int]$response.StatusCode) }
        $data = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $catalogMatches = @($data.photos).Count -eq 5 -and $null -eq $data.nextCursor
        foreach ($item in $catalog) {
            $photo = @($data.photos | Where-Object id -eq $item.id)
            $catalogMatches = $catalogMatches -and $photo.Count -eq 1 -and $photo[0].downloadUrl -eq ('/' + $item.originalKey) -and $photo[0].sizeBytes -eq $item.sizeBytes -and $photo[0].sha256 -eq $item.sha256
        }
        Record '获邀 API 五条资料' $catalogMatches 'HTTP 200，核对下载路径、大小、哈希和分页结束标记'
    } finally { $response.Dispose() }

    foreach ($item in $catalog) {
        $response = Request ($origin + '/' + $item.originalKey) $valid
        try {
            if ([int]$response.StatusCode -ne 200) { Record ('原图 ' + $item.id) $false ('HTTP ' + [int]$response.StatusCode); continue }
            $path = Join-Path $output ($item.id + '.jpg')
            $file = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
            try { $null = $response.Content.CopyToAsync($file).GetAwaiter().GetResult() } finally { $file.Dispose() }
            $size = (Get-Item -LiteralPath $path).Length
            $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            Record ('原图 ' + $item.id) ($size -eq $item.sizeBytes -and $hash -eq $item.sha256) ($size.ToString() + ' bytes，SHA256 与原图资料比较')
        } finally { $response.Dispose() }
    }

    $photoUrl = $origin + '/' + $catalog[0].originalKey
    $cases = @(
        @{ Name = 'API 无邀请'; Url = $origin + '/api/photos'; Cookie = '' },
        @{ Name = 'API 过期邀请'; Url = $origin + '/api/photos'; Cookie = $expired },
        @{ Name = 'API 篡改签名'; Url = $origin + '/api/photos'; Cookie = $tampered },
        @{ Name = '相册页无邀请'; Url = $origin + '/photos/index.html'; Cookie = '' },
        @{ Name = '原图无邀请'; Url = $photoUrl; Cookie = '' },
        @{ Name = '原图过期邀请'; Url = $photoUrl; Cookie = $expired },
        @{ Name = '原图篡改签名'; Url = $photoUrl; Cookie = $tampered },
        @{ Name = 'Lambda URL 匿名直连'; Url = $apiConfig.functionUrl.TrimEnd('/') + '/api/photos'; Cookie = '' },
        @{ Name = 'S3 原图匿名直连'; Url = 'https://cj-job-portfolio-20261024-resume.s3.ap-northeast-1.amazonaws.com/' + $catalog[0].originalKey; Cookie = '' }
    )
    foreach ($case in $cases) {
        $response = Request $case.Url $case.Cookie
        try { Record $case.Name ([int]$response.StatusCode -eq 403) ('HTTP ' + [int]$response.StatusCode) }
        finally { $response.Dispose() }
    }
    foreach ($name in @('index.html', 'app.js')) {
        $response = Request ($origin + '/' + $name) $valid
        try {
            $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
            $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
            Record ('线上文件 ' + $name) ([int]$response.StatusCode -eq 200 -and $hash -eq (Get-FileHash -LiteralPath "$root/dist/$name" -Algorithm SHA256).Hash) '与本地文件 SHA256 比较'
        } finally { $response.Dispose() }
    }
    $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'results.json') -Encoding utf8
    Write-Output ('结果：' + $results.Count + ' 项，失败 ' + @($results | Where-Object { -not $_.passed }).Count)
    Write-Output ('本地证据：' + $output)
    if (@($results | Where-Object { -not $_.passed }).Count) { exit 1 }
} finally { $rsa.Dispose(); $client.Dispose() }
