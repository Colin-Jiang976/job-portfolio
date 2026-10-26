# 下一对话交接

更新：2026-10-26（日本时间）。用户将自行开新对话，助手不要自动创建聊天。

## 当前接续点

首版照片下载 App 已上线：现有私有 S3/CloudFront 加 cj-photo-api Python 3.12 Lambda、AWS_IAM 函数 URL、Lambda OAC、受同一邀请保护的 api/* 行为和 cj-photo-catalog DynamoDB。源站名现为 cj-photo-api；本人反馈首页入口→相册→下载成功。接口/页面/五张原图已上传，不要重复创建、上传或改名。实际配置在 config/photo-api.json。

2026-10-26 独立线上 17 项通过：五条资料、五张 JPG 共 64,773,953 字节及 SHA256、接口/原图无邀请/过期/篡改拒绝、相册页无邀请拒绝、Lambda/S3 匿名直连拒绝、首页两文件与本地哈希一致。本地证据 .local/photo-app/verification-20261026-033121-561/（忽略，不提交）。脚本 scripts/Test-PhotoDeployment.ps1 可复用；已通过的不重复测，不当作百万规模证明。

当前进入收尾：下一项本人在 Billing 设置 USD 5/月费用提醒；尚无预算完成反馈。日志保留/资源上限待核对，费用提醒不是硬停止。旧 main/ 副本暂留，通用缩略图自动化、搜索、上传后台和 Log Check 联动暂不加。原尺寸 JPG 下载采用 photo-originals/main/{id}.jpg；此前缺前缀导致 Forbidden 已修复。

保留个人 content.js 原字节（SHA256 FD7E68B34AC74207007B5F4AF345482ADE8886FA4A5AD374EDC54B39CBFD874B）。首页入口仅改 index.html/app.js，三语和传递语言已验；首页旧介绍/页脚未顺手改写。私有 GitHub 保留原历史，按阶段保存；最新提交以 Git 记录为准。本人要求减少细致手册，保持简短；每轮一个完整配置环节，不按单个按钮拆分，不把成功认定为理解。

## 旧阶段记录（以下状态以当前接续点为准）

最新推进决定：本人决定今天先完成首版上线，代码理解可随后进行；条件搜索留下一版。相册已统一隐藏可见标题和文件名，原名称仅作辅助阅读；本地五卡片/五下载入口及无可见标题/文件名已核对。当前指导原 Lambda 换 Python、本人 CloudShell 用 scripts/grant-photo-read.sh 加指定 main 相册 Query 权限并测试，尚未收到这组结果；之后接受邀请保护的 CloudFront API，再上传原图和页面验收。不要照旧的“暂停配置”继续停在纯讲解。

当前实际版本：本人要求暂不加功能，仅改 Python 后端和去掉三语照片名必填；本地已完成，入口 backend/photo-api/lambda_function.py，Python 3.12，处理程序 lambda_function.lambda_handler。八项 Python 测试及浏览器可选标题回退通过，旧 JS 后端/本地服务已移除，界面 JS 与三语保留。现有五张名称保留，新增照片可不命名、只填一个名称或部分译名，缺省显示文件名。部署包 .local/photo-app/deploy-20261025-210328-778/photo-api.zip。DynamoDB 五条资料已由本人导入，云端 Lambda 仍是旧 Node.js 包；本轮未改云端或加分类/Log Check 联动。本人希望之后慢慢读，不安排当下操作/测试。恢复后先确认阅读需要，再在原函数迁移运行时/处理程序/ZIP，无需重建表或重新导入旧五条。

GitHub 已完成本轮上传：私有仓库 https://github.com/Colin-Jiang976/job-portfolio ，基线 fb2e902、本地照片应用实现 4b0cc37 已推送 main，远程 SHA 已核对。下文“实现待推送/仍未提交”属于此前阶段记录。当前先打开本地五张样本应用体验，再由本人控制台创建 DynamoDB 表；AWS 动态资源尚未创建。

最新实际进展：本人接受首版建议，已完成本地照片应用、只读 Lambda 代码和部署材料，尚未创建 DynamoDB/Lambda 或更新 AWS。五张原图下载字节/哈希、53 条合成分页、输入与错误处理程序测试共七项通过；浏览器三语/五图/大图/实际下载已核对。390px DOM 单列无横溢，手机截图工具失败，默认尺寸已恢复。说明见 job-portfolio/docs/照片应用第一版.md。本人已创建私有 GitHub 仓库 https://github.com/Colin-Jiang976/job-portfolio ，基线 fb2e902 已推送，后续实现提交看 Git 历史。原 roleValue 试改已随基线保存，字节未变，不再是未提交状态，不擅自定稿。密钥与完整邀请、原 JPG、生成材料继续忽略。下一步先本人体验本地，再本人控制台建表及后续 CloudShell 解释；理解状态未获新反馈。

最新决定：本人明确选择 DynamoDB，首版不采用常规 RDS/Aurora。下一步集中确认下载形式、上传维护、分页浏览范围与预算；已确认下载原尺寸修图 JPG、保持三语与现有邀请保护。实施前计划在 job-portfolio/docs/PHOTO_APP_PLAN.md。本人要求合适时放到 GitHub，建议首版范围确定后、动态开发前建私有基线；本地有 4 个提交、无远程，上级接续文档尚不在仓库内，.openai/hosting.json 已被跟踪。仓库名/公开范围未确认，未提交或推送，密钥/邀请继续排除。本段优先于下文“尚未选型”的历史比较。

最新选型偏好：本人不喜欢 SQL，倾向不用常规 RDS，询问 Aurora Serverless。PHOTO_APP_FEASIBILITY.md 已补 Aurora v2 自动暂停、东京单价与计算示例。助手优先建议 DynamoDB；本人尚未选定，不追加默认 SQL 学习任务。继续先讨论用途、扩展与预算，不创建资源。

最新优先顺序：本人认为此前跳过了可行性评价，要求先说明照片下载 App 是否值得作为云岗位作品、几十张微缩版如何面向几万/百万张扩展、DynamoDB/RDS 额度与正常付费金额、SQL 学习价值。下载确定提供本人修图后原尺寸 JPG，方式未定。PHOTO_APP_FEASIBILITY.md 已记录官方价格与假设推算，尚未确认数据库或实施，不把扩展设计写成百万规模实测。后续先讨论评估结论与预算，再定最小功能。

静态网站与邀请访问本轮验收完成。用户最新澄清：原计划是上传几十张照片并实现供人浏览和下载的照片下载 Web App，作为求职时可操作的作品；仅静态履历不能完成目标。下一阶段用途已明确，需围绕应用确定数据库/接口、上传方式、单张/批量及下载文件规格。优先比较 DynamoDB 为建议，未获选型确认；不自动创建资源、上传后台或日志联动。用户询问数据库是否能保障文字安全，应解释权限与返回内容的边界，不记成已理解。照片说明可纳入，独立文章系统仍非必需。页脚等小改动、缓存专项练习与页面打磨继续暂缓。方案见 NEXT_STAGE_DATABASE_OPTIONS.md 最新应用草案。

## 已有部署，继续复用

- 区域：东京 ap-northeast-1。
- S3 私有桶：cj-job-portfolio-20261024-resume；阻止所有公有访问开启。
- CloudFront 分配：E1EXJ282JJY07Q；默认根对象 index.html。
- 网站：https://dh0h1qa1vbzc5.cloudfront.net/ 。现在普通根网址在没有凭证时被拒绝，这是预期结果。
- 行为：invite/* 公开通用邀请入口；默认 (*) 使用可信密钥组保护其余内容。
- 公钥 ID：KCCXWBSABUX95。
- 密钥组 ID：e187cfe4-80f0-48d0-95ab-31675bf99a4d。
- 默认邀请有效 30 天，可转发，重新打开和转发不续期。进入后根网址不包含完整邀请，转发使用最初完整链接。
- 未启用可选 WAF、Origin Shield，未为本轮新增 Route 53 托管区域；不新建重复分配，不升级账号。

## 验证与边界

本人反馈三语、五张照片和大图正常。OAC 签名设置有截图证据，桶策略限定上述分配只读，S3 首页匿名直连 AccessDenied；本人提供 CloudFront 照片直连 MissingKey。

Codex 已执行 11 组本地浏览器场景及 8 项真实 CloudFront HEAD 测试。实际 200：公开入口、有效凭证首页、有效凭证照片、同一凭证在另一新 HTTP 客户端读取首页。实际 403：无凭证首页/照片、篡改到期但保留原签名、签名正确但已过期。HEAD 不等于全部浏览器和全部文件的完整下载验证。不要重复整套已通过测试，除非新改动需要。

账号据本人反馈为免费计划，剩余 177 天，抵扣金 140 USD（2026-10-25）；准确到期日未核实。Bills 截图各列示服务及总额 USD 0.00，不推断以后用量永久为零。日常身份即使尝试授权仍不能看账单，用户要求先放着，后续需要时再排查。

## 文件和密钥

- AGENTS.md：项目规则，优先读取。
- JOB_SEARCH_SITE_BLUEPRINT.md：方向和已确认约定。
- PROJECT_STATUS.md：详细进度，含历史记录；最新阶段和“下一步”优先。
- NEXT_STAGE_DATABASE_OPTIONS.md：下一阶段用途与方案比较，均为候选。
- job-portfolio/dist/：当前网站，共原有文件加 invite/ 四个通用入口文件。
- job-portfolio/dist/content.js：个人资料三语文案，已有本人未提交的日文 roleValue 试改「クラウド・インフラ設計・構築」，必须保留；当前 SHA256 为 FD7E68B34AC74207007B5F4AF345482ADE8886FA4A5AD374EDC54B39CBFD874B。试改已上传，但不定为最终定位。
- job-portfolio/dist/photos.js：五张照片的路径、顺序和标题键；新数据库资料尚未替代它。
- job-portfolio/dist/invite/content.js：公开入口的通用三语提示，不公开根 content.js 中的个人资料。
- job-portfolio/config/cloudfront-invitation.json：域名、公钥及密钥组等非秘密配置。
- job-portfolio/scripts/New-CloudFrontSigningKey.ps1：PowerShell 7 生成 RSA 2048 密钥，拒绝覆盖已有文件。
- job-portfolio/scripts/New-PortfolioInvitation.ps1：本地生成 30 天邀请，不调用 AWS。
- job-portfolio/scripts/Test-CloudFrontInvitation.ps1：8 项真实站点只读验收，不输出凭证。
- job-portfolio/scripts/test-invitation.cjs：本地浏览器测试；Playwright 可使用本机 Edge。
- job-portfolio/CloudFront邀请访问准备.md：邀请机制、部署与恢复步骤、测试证据。

私钥在 job-portfolio/.local/cloudfront/private-key.pem，公钥为同目录 public-key.pem；密钥和完整邀请文件均被 .gitignore 忽略，不在 dist/ 内。只需核对存在，不输出私钥或完整凭证。本地已有 invitation-20261025-052303-45c16599.txt，生成时设定到期为 2026-11-24 14:23:03 +09:00；后续按需重新生成。

## 工作与理解状态

- 使用中文，用户自行操作 AWS 控制台，Codex 准备代码、解释用途并核对证据；后续若需 CLI 或改为助手部署，先明确执行方式和账号权限。
- 用户反馈单项等待的测试太琐碎，一轮可合并几项相关操作，异常再拆解；优先文字，必要时截图。
- 用户表示签名与密钥“大概理解”，也曾不知道如何提问；主动串联请求流程，不把照做成功视为掌握。
- 页面设计和整体内容打磨继续暂停。数据库用途、选型、管理后台、照片下载、业务工具展示、Log Check 去留均未确定。
- 本轮未提交代码；除本人原 content.js 修改外，有邀请实现及文档等未提交文件，先核对 git status，不重置、不自动提交或部署。
- 网站仍有“待 AWS 部署”等过时文案，用户选择暂缓小改动，不因此自动修正文案。

## 可复制的新对话开场

请接续求职网站与 DynamoDB 照片下载应用。先读 AGENTS.md、JOB_SEARCH_SITE_BLUEPRINT.md、PROJECT_STATUS.md、本交接及 job-portfolio/docs/照片应用第一版.md，核对 Git 状态与实际代码。首版已确认单张原 JPG、控制台上传与批量资料、每页 24 张、约 USD 5/月预算目标。本地五张样本已验证，私有 GitHub 仓库已推送；AWS 静态站与 30 天邀请验收完成，动态数据库/接口尚未部署。先帮助我串起读取资料到下载原文件的流程，再由我操作控制台逐组部署，不自动创建重复资源或上传后台、ZIP、日志联动。保留本人文案字节内容，不把操作成功当作理解；用中文、一轮合并相关步骤，异常再拆解。
