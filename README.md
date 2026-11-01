# 求职网站与照片下载应用

运行在AWS的个人求职网站，提供日中英页面、邀请访问、摄影浏览与原尺寸JPG下载、项目示例和日志报告。本人负责需求、取舍、照片与内容、AWS操作及反馈；Codex协助设计、代码、翻译和验证。操作成功不等于独立掌握全部实现。

## 当前状态（2026-11-01）

- 真实92张照片、9个地点；列表四页24/24/24/20，支持按地点筛选。
- 私有S3和CloudFront提供页面、预览及原JPG；Python Lambda从DynamoDB Query读取目录，JPG不经过Lambda转发。
- 本机维护入口支持准备新照片、看图批量选地点、本人确认后发布；无公众上传后台。
- 照片API日志经本地整理，由本人按需投递已有Cloud Log Check。正常报告来自AWS，受控故障及格式示例来自本地；不是实时采集。
- 工具示例/证据、联系方式与可配置履历下载已上线；正式文件未提供，当前没有假下载按钮。
- 本轮静态更新已有针对性线上核对和本人真实手机正常反馈。未验证百万图片导入或大规模负载。
- 源码已删除首页打印按钮，该小修尚未发布网站。个人资料与正式履历后补。

## 代码入口

| 位置 | 内容 |
| --- | --- |
| [dist](dist) | HTML/CSS/JavaScript、三语文字与首页五张WebP展示副本 |
| [dist/photos](dist/photos) | 相册、地点显示翻译、预览与下载链接 |
| [backend/photo-api](backend/photo-api) | Python3.12只读API、地点目录与分页 |
| [Photo-Maintenance.cmd](Photo-Maintenance.cmd) | 本机照片维护菜单 |
| [scripts](scripts) | Python/Node.js准备与发布、地点维护、本地看图页面及针对性检查 |
| [Site-Release.cmd](Site-Release.cmd) | 静态检查、增量包及本地副本恢复 |
| [dist/log-check](dist/log-check) | 来源与执行位置明确的脱敏报告 |
| [dist/work-tools](dist/work-tools) | PowerShell工具的静态示例与证据摘要 |
| [docs](docs) | 设计、维护、验证与限制 |

网页使用JavaScript，照片API及Log Check核心使用Python；照片准备仍调用部分Node.js脚本。PowerShell工具在独立仓库，Java/LeetCode是独立学习记录。

## 本地查看

先在本机复制不含个人值的配置示例：

    Copy-Item dist/contact.example.js dist/contact.private.js

contact.private.js由.gitignore排除。需要显示联系方式时，仅在该本地文件填写；保持空值则不显示联系方式。该文件供受邀请保护的网站部署使用，不提交到源码仓库。

运行：

    python -m http.server 8767 --bind 127.0.0.1 --directory dist

打开 http://127.0.0.1:8767/index.html?lang=zh 。首页、工具示例和报告可本地查看。相册的/api/photos需要真实后端或本地API替身，静态HTTP服务不会生成接口；本地预览不执行CloudFront邀请认证。

照片准备需要Python、Pillow、Node.js；云端维护另外使用AWS CLI的维护者临时身份。固定CMD入口按当前本机运行环境配置，使用方式见维护文档。

## 维护与验证说明

- [照片维护设计](docs/照片维护设计说明.md)：维护者发布链与访客读取链。
- [照片批量维护](docs/照片批量维护.md)：准备、确认发布及回执。
- [拍摄地点筛选](docs/照片地点筛选.md)：目录、稳定ID与显示翻译。
- [Log Check交接](docs/LogCheck日志交接.md)：按需交接和报告来源。
- [网站更新与恢复](docs/网站更新与恢复.md)：静态更新与本地副本恢复，不是云端全栈灾难恢复。
- [作品与履历入口](docs/作品入口与履历下载.md)：工具证据、源码直链及后补材料。
- docs/project-notes/保存早期阶段快照；当前源码与已发布状态分别以实际文件和发布记录为准。

检查只针对相关改动，历史检查计数不相加。预算提醒和用量限制不是费用硬封顶；92张成功不是百万规模证明，工具代码运行速度不是人工节时。

## 相关仓库

- [Cloud Log Check](https://github.com/Colin-Jiang976/cloud-log-check)：检查器和Terraform。
- [运维辅助工具](https://github.com/Colin-Jiang976/my-work-tools)：原有版本、审阅版与虚构演示。
- [Java / LeetCode](https://github.com/Colin-Jiang976/leetcode-java)：独立学习记录。

通过仓库链接直接查阅，不安排邮件索取。仓库可见性由本人在GitHub决定。

## 源码与运行资料

仓库包含代码、说明和分享用示例。网站联系邮箱和电话放在被忽略的dist/contact.private.js，不硬编码进HTML/应用脚本；公开仓库只提供空白contact.example.js。.local/保存本机密钥、完整邀请、原JPG/批次、回执和原始验证资料，由.gitignore排除，不属于源码提交。首页WebP和脱敏报告JSON是明确的展示资产。网站邀请访问和GitHub仓库可见性分别管理。
