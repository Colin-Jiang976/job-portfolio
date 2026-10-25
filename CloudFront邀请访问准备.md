# CloudFront 邀请访问准备

本文件记录 2026-10-25 开始的准备工作，访问限制尚未上线。

当前进度：本人已完成上传入口和默认行为关联，反馈有效邀请可以进入、无凭证照片返回 MissingKey。Codex 的 11 组本地浏览器场景及 8 项真实 CloudFront HEAD 测试已通过（见文末），本轮邀请访问验收收尾。本人表示大概理解并询问行为含义，不等于已独立掌握实现。完整第二浏览器页面流程及未来新增下载功能不因 HEAD 测试而视为已全部验证。

- 公钥 ID：`KCCXWBSABUX95`
- 密钥组 ID：`e187cfe4-80f0-48d0-95ab-31675bf99a4d`
- 非秘密配置：`config/cloudfront-invitation.json`

## 这些设置分别负责什么

| 项目 | 保存位置 | 在本方案中的职责 |
| --- | --- | --- |
| 私钥 | 本人电脑，不在 dist/ 内 | 给包含访问范围和到期时间的授权信息签名，生成之后可分享的凭证 |
| 公钥 | 已上传 CloudFront | 核验凭证签名是否与对应私钥匹配；持有公钥不能代替私钥签发新凭证 |
| 密钥组 | CloudFront | 汇集允许验签的公钥；之后将这一组关联到需要保护的访问行为 |

未来访问流程：本人在本地生成邀请链接 → HR 点击链接，由邀请入口将凭证交给浏览器 → 浏览器请求网页及图片时携带签名 Cookie → CloudFront 核对签名、资源范围和到期时间 → 通过后返回缓存内容，或按需回源读取 S3。

OAC 处理 CloudFront 向 S3 取文件时的身份验证；此次签名 Cookie 处理访客向 CloudFront 请求文件时的授权。两者保护的位置不同。创建公钥和密钥组只是准备验签工具，尚未使网站变为邀请访问。

## 当前两条行为如何分工

行为是一组按 URL 路径选用的请求处理规则，也控制源站、HTTPS、缓存和访问授权。CloudFront 从上往下匹配，第一条命中后即采用该规则，不再继续套用后面的规则。

| 请求路径 | 采用的行为 | 本网站的授权处理 |
| --- | --- | --- |
| /invite/index.html、/invite/app.js 等 | invite/*，优先级 0 | 公开通用入口，不含个人资料；入口将原始邀请凭证交给浏览器 |
| /、/index.html、/content.js、/assets/photos/… | 默认 (*)，最后处理 | 验证签名 Cookie 后才提供页面、文案和图片 |

默认不是额外开放的入口，它是保护其余内容的兜底规则。公开入口只负责领取凭证，默认规则才负责拒绝未获授权的资料请求。已经通过邀请的同一浏览器可携凭证直接访问普通网址，因此无凭证测试应使用没有旧 Cookie 的新无痕会话。

## 已确认的目标

- 邀请链接默认生成起 30 天有效，转发不续期。
- HR 可将链接转发给负责人，不要求注册、登录或邮箱验证。
- 获准浏览器可正常加载三语页面、图片及未来实现的下载功能。
- 普通网址和缺少有效凭证的文件请求应被拒绝。
- S3 与 CloudFront 继续使用现有资源，不新增分配。

## 本地密钥

`scripts/New-CloudFrontSigningKey.ps1` 使用 PowerShell 7 和系统 .NET 加密库生成 RSA 2048 密钥，生成前实际签名/验签，并拒绝覆盖已有文件。

密钥保存在仓库内的 `.local/cloudfront/`，该目录已加入 `.gitignore`，也不在上传网站的 `dist/` 内。

- `public-key.pem`：公钥，可完整复制到 CloudFront Public keys；必须包含 BEGIN PUBLIC KEY 和 END PUBLIC KEY 两行。
- `private-key.pem`：私钥，仅在本地生成邀请凭证时使用，不上传到网站、CloudFront 或聊天。丢失后需要更换密钥；本地应自行保管。

公钥用于 CloudFront 验证签名；私钥用于本地生成签名。两者不是 AWS Access Key，也不是 OAC。

## 由本人操作控制台

1. CloudFront → Public keys（公有密钥）→ Create public key。
2. Name 填 `cj-portfolio-invite-key-20261025`，Key value 粘贴 `public-key.pem` 全文，创建后记录公钥 ID。
3. CloudFront → Key groups（密钥组）→ Create key group。
4. Name 填 `cj-portfolio-invite-viewers`，将刚才的公钥加入组，创建后记录密钥组 ID。

本阶段只创建公钥与密钥组，不把它们关联到分配行为，不改变现有访问方式。

## 本地生成与入口实现

`scripts/New-PortfolioInvitation.ps1`（PowerShell 7）读取现有私钥和上述配置，默认生成起 30 天到期，使用 RSA SHA256 签名并作本地验签。它将完整链接保存在 `.local/cloudfront/invitation-*.txt`，不调用 AWS，不将私钥或凭证写入 `dist/`。以后重新生成邀请使用此脚本，不重新生成密钥。

PowerShell 7 中，在 job-portfolio 目录运行：

```powershell
./scripts/New-PortfolioInvitation.ps1
```

若系统没有安装 PowerShell 7，可使用本机 Codex 已提供的运行时：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe" -NoProfile -File './scripts/New-PortfolioInvitation.ps1'
```

`dist/invite/` 仅包含通用入口的四个文件，不包含个人资料或密钥。该入口的三语文字在 `dist/invite/content.js`，个人资料仍在根目录 `dist/content.js`；这样公开入口不需要读取受保护的个人资料。

邀请凭证放在 URL 的 `#` 片段，浏览器请求服务器时不发送这一部分。入口读取后立即清除当前地址栏片段，写入同一域名的 Secure、SameSite=Lax 签名 Cookie，再以 HEAD 请求 `/index.html`。CloudFront 验证通过后进入根首页。浏览器脚本只检查格式和到期，真正的签名和权限验证由 CloudFront 负责；默认行为尚未启用签名验证时，HEAD 成功不代表访问限制已生效。

此轻量实现由浏览器脚本设置 Cookie，因此 Cookie 不是 HttpOnly；入口采用同源脚本和严格 CSP，不引入第三方脚本。若未来加入第三方脚本、富文本输入或后台，应重新评估凭证发放和脚本注入风险。链接可被持有人转发，已保存内容无法在到期后收回。

进入后地址栏会变为普通网站根网址。转发时应转发收到的原始完整邀请链接，不能用进入后的普通根网址替代。

## 由本人上传并关联（按顺序）

1. 在现有 S3 桶根目录上传本地 `dist/invite/` 文件夹，应新增 `invite/index.html`、`invite/content.js`、`invite/app.js`、`invite/styles.css` 四个对象；不上传项目其他目录或 `.local/`。
2. CloudFront → 当前分配 `E1EXJ282JJY07Q` → Behaviors → Create behavior。路径填写 `invite/*`，源站选择现有 S3 源站；Viewer protocol policy 为 Redirect HTTP to HTTPS，方法 GET/HEAD，缓存策略 CachingOptimized，Restrict viewer access 为 No。保存。
3. 待部署完成后，打开 `https://dh0h1qa1vbzc5.cloudfront.net/invite/index.html`（无凭证）。应看到通用的“需要邀请链接”提示，可切换三语；不能是 AccessDenied。此项不通过先检查文件路径和入口行为，不启用下一步限制。
4. 选中第二行“默认 (*)”左侧圆圈，点击“编辑”。在编辑页查找“限制查看器访问（使用签名 URL 或签名 Cookie）”（Restrict viewer access），可用 Ctrl+F 搜索“签名”辅助定位，设为“是”；选择“可信密钥组”（Trusted key groups，推荐），选入 `cj-portfolio-invite-viewers`，核对组 ID 为 `e187cfe4-80f0-48d0-95ab-31675bf99a4d`；保留现有源站、HTTPS 和缓存配置。保存并等部署完成。不要把限制加在 `invite/*` 上。若编辑页没有对应字段，先提供该实际页面的必要截图，确认入口再操作；行为列表截图本身不显示这一配置，不能据此断定有无启用。
5. 用全新无痕窗口打开普通根网址、`/content.js` 和一张照片的普通网址，预期拒绝访问。再打开本地生成的完整邀请链接，预期进入网站并正常显示三语和五张照片；在另一全新浏览器使用同一原始邀请链接应同样成功。

这是 CloudFront 访客访问限制，与 OAC/桶策略不冲突。两项行为最终应为：`invite/*` 公开通用入口，Default (*) 通过可信密钥组保护其余网站资源。如果列表已有其他行为，逐项核对，不能只限制首页。

真实 CloudFront 已通过篡改和到期拒绝测试，S3 匿名直连此前已验证拒绝。未来新增下载功能需另作授权验证。当前照片显示和大图并不等于已实现原图下载或简历下载。

## 已取得的验收证据

`scripts/Test-CloudFrontInvitation.ps1` 只对配置中的现有 CloudFront 网站发出 HEAD 请求，不更改云端配置，也不显示访问凭证。测试在每次请求使用新客户端，避免旧 Cookie 干扰。2026-10-25 实际结果：

| 请求 | 预期及实际状态 |
| --- | --- |
| 无凭证读取公开邀请入口 | 200 |
| 无凭证读取首页 | 403 |
| 无凭证读取照片 | 403 |
| 有效凭证读取首页 | 200 |
| 有效凭证读取照片 | 200 |
| 同一有效凭证在另一新 HTTP 客户端读取首页 | 200 |
| 将到期时间延长但沿用旧签名 | 403 |
| 签名正确但到期时间已经过去 | 403 |

测试凭证只在运行时内存中生成，不改变已有 30 天邀请文件，也不需要实际等待 30 天。到期测试是向 CloudFront 提交签名正确的过期凭证，独立于入口页面的本地时间判断。HEAD 只确认服务器响应，不代替所有浏览器、所有文件和下载交互测试。

## 故障恢复

若配置后连有效邀请也无法进入，先检查 `invite/*` 是否公开、对象路径是否正确、密钥组是否包含上述公钥、公钥是否为本地对应公钥、分配部署是否完成。需要恢复先前公开访问时，可将 Default (*) 的 Restrict viewer access 改回 No，待部署完成；这会恢复公开访问，仅适用于当前尚未加入敏感个人资料的恢复场景。无论排查或恢复，都不要关闭 S3 的阻止公有访问，不修改 OAC，不把私钥上传。

## 官方参考

- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-trusted-signers.html
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-signed-cookies.html
