#Requires -Version 7.0
# 只在本地生成签名密钥，不调用 AWS，也不修改 dist/。
$ErrorActionPreference = 'Stop'
$keyDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '../.local/cloudfront')
)
$privatePath = Join-Path $keyDirectory 'private-key.pem'
$publicPath = Join-Path $keyDirectory 'public-key.pem'

foreach ($keyPath in @($privatePath, $publicPath)) {
    if (Test-Path -LiteralPath $keyPath) {
        throw '密钥文件已存在，已停止生成，避免覆盖。请继续使用现有密钥。'
    }
}

$signer = [System.Security.Cryptography.RSA]::Create(2048)
$verifier = [System.Security.Cryptography.RSA]::Create()
try {
    $privatePem = $signer.ExportPkcs8PrivateKeyPem()
    $publicPem = $signer.ExportSubjectPublicKeyInfoPem()
    $verifier.ImportFromPem($publicPem)

    # 实际签名和验签，确认公钥与私钥匹配。
    $probe = [System.Text.Encoding]::UTF8.GetBytes('cloudfront-signing-key-check')
    $signature = $signer.SignData(
        $probe,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    if (-not $verifier.VerifyData(
        $probe,
        $signature,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
    )) {
        throw '签名验证失败，未保存密钥。'
    }

    [System.IO.Directory]::CreateDirectory($keyDirectory) | Out-Null
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    foreach ($keyFile in @(
        @{ Path = $privatePath; Text = $privatePem },
        @{ Path = $publicPath; Text = $publicPem }
    )) {
        # CreateNew 在文件已存在时失败，防止覆盖已有密钥。
        $stream = [System.IO.File]::Open(
            $keyFile.Path,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $bytes = $utf8.GetBytes($keyFile.Text + "`n")
            $stream.Write($bytes, 0, $bytes.Length)
        }
        finally { $stream.Dispose() }
    }
    Write-Output 'RSA 2048 密钥已在本地生成，SHA256 签名/验签通过。'
    Write-Output "可上传 CloudFront 的公钥文件：$publicPath"
    Write-Output '私钥位于同一目录，仅供本地签名使用；不要上传到 S3、CloudFront 或聊天。'
}
finally {
    $verifier.Dispose()
    $signer.Dispose()
}
