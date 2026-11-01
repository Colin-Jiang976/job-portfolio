#Requires -Version 7.0
# 只读核对本轮首页/报告文件及报告访问边界；不请求照片API或原JPG，不输出凭证。
param([switch]$HomepageOnly)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content -LiteralPath "$root/config/cloudfront-invitation.json" -Raw | ConvertFrom-Json
$origin = 'https://' + $config.distributionDomain
if ($origin -ne 'https://dh0h1qa1vbzc5.cloudfront.net') { throw '仅核对现有求职网站。' }
$output = Join-Path $root ('.local/log-check/verification-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fff'))
[IO.Directory]::CreateDirectory($output) | Out-Null
$rsa = [Security.Cryptography.RSA]::Create()
$handler = [Net.Http.HttpClientHandler]::new()
$handler.UseCookies = $false
$handler.AllowAutoRedirect = $false
$client = [Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(30)
$results = [Collections.Generic.List[object]]::new()
function New-Cookie([long]$Expiry) {
    $policy = [ordered]@{ Statement = @(@{ Resource = $origin + '/*'; Condition = @{ DateLessThan = @{ 'AWS:EpochTime' = $Expiry } } }) } | ConvertTo-Json -Depth 8 -Compress
    $signature = $rsa.SignData([Text.Encoding]::UTF8.GetBytes($policy), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $encode = { param([byte[]]$Bytes) [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('=', '_').Replace('/', '~') }
    'CloudFront-Policy=' + (& $encode ([Text.Encoding]::UTF8.GetBytes($policy))) + '; CloudFront-Signature=' + (& $encode $signature) + '; CloudFront-Key-Pair-Id=' + $config.publicKeyId + '; CloudFront-Hash-Algorithm=SHA256'
}
function Read-Page([string]$Url, [string]$Cookie = '') {
    $message = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Url)
    $response = $null
    try {
        if ($Cookie) { $null = $message.Headers.TryAddWithoutValidation('Cookie', $Cookie) }
        $response = $client.SendAsync($message).GetAwaiter().GetResult()
        [pscustomobject]@{ status = [int]$response.StatusCode; bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult(); cache_control = [string]$response.Headers.CacheControl }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $message.Dispose()
    }
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
    $paths = @('index.html', 'app.js', 'content.js', 'architecture.css', 'log-check/index.html', 'log-check/app.js', 'log-check/content.js', 'log-check/styles.css', 'log-check/reports.json')
    if ($HomepageOnly) { $paths = @('index.html', 'app.js', 'content.js', 'architecture.css') }
    foreach ($path in $paths) {
        $page = Read-Page ($origin + '/' + $path) $valid
        $local = [IO.File]::ReadAllBytes((Join-Path "$root/dist" $path))
        $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($page.bytes))
        $expected = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($local))
        Record ('获邀文件 ' + $path) ($page.status -eq 200 -and $hash -eq $expected) ('HTTP ' + $page.status + '，SHA256 ' + (@('不一致', '一致')[[int]($hash -eq $expected)]) + '，Cache-Control=' + $page.cache_control)
        if ($page.status -eq 200) {
            $save = Join-Path $output $path
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($save)) | Out-Null
            [IO.File]::WriteAllBytes($save, $page.bytes)
        }
        if ($path -eq 'index.html' -and $page.status -eq 200) {
            $html = [Text.Encoding]::UTF8.GetString($page.bytes)
            Record '首页报告入口' ($html -match 'href="log-check/index.html\?lang=ja"[^>]*data-log-check-link') '核对线上HTML的实际链接'
        }
        if ($path -eq 'log-check/reports.json' -and $page.status -eq 200) {
            $data = [Text.Encoding]::UTF8.GetString($page.bytes) | ConvertFrom-Json
            $items = @($data.reports)
            $matches = $items.Count -eq 3 -and $items[0].status -eq 'OK' -and $items[0].source -eq 'cloud-api' -and $items[0].engine -eq 'aws' -and $items[1].status -eq 'ALERT' -and $items[1].engine -eq 'local' -and $items[2].status -eq 'INVALID' -and $items[2].engine -eq 'local' -and $null -eq $items[2].total_records
            Record '报告来源与计数边界' $matches '正常AWS；受控失败/格式测试local；INVALID条数null'
        }
    }
    $boundaryPaths = @('log-check/index.html', 'log-check/reports.json')
    if ($HomepageOnly) { $boundaryPaths = @() }
    foreach ($path in $boundaryPaths) {
        foreach ($case in @(@{ name = '无邀请'; cookie = '' }, @{ name = '过期邀请'; cookie = $expired })) {
            $page = Read-Page ($origin + '/' + $path) $case.cookie
            Record ($path + ' ' + $case.name) ($page.status -eq 403) ('HTTP ' + $page.status)
        }
        $page = Read-Page ('https://cj-job-portfolio-20261024-resume.s3.ap-northeast-1.amazonaws.com/' + $path)
        Record ($path + ' S3匿名直连') ($page.status -eq 403) ('HTTP ' + $page.status)
    }
    $rootPage = Read-Page ($origin + '/') $valid
    $rootHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($rootPage.bytes))
    $indexHash = (Get-FileHash -LiteralPath "$root/dist/index.html" -Algorithm SHA256).Hash
    Record '根路径首页' ($rootPage.status -eq 200 -and $rootHash -eq $indexHash) ('HTTP ' + $rootPage.status + '，与新版index核对')
    $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'results.json') -Encoding utf8
    Write-Output ('本轮报告路径核对：' + $results.Count + ' 项，失败 ' + @($results | Where-Object { -not $_.passed }).Count)
    Write-Output ('证据目录：' + $output)
    if (@($results | Where-Object { -not $_.passed }).Count) { exit 1 }
} finally { $rsa.Dispose(); $client.Dispose() }
