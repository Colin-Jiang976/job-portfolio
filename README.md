# 求职网站与照片下载应用

运行在AWS的个人求职网站，提供日中英页面、邀请访问、摄影浏览与原尺寸JPG下载、项目示例和日志报告。本人负责需求、取舍、照片与内容、AWS操作及反馈；Codex协助设计、代码、翻译和验证。操作成功不等于独立掌握全部实现。

## 当前状态（2026-11-01）

- 真实92张照片、9个地点；列表四页24/24/24/20，支持按地点筛选。
- 私有S3和CloudFront提供页面、预览及原JPG；Python Lambda从DynamoDB Query读取目录，JPG不经过Lambda转发。
- 本机维护入口支持准备新照片、看图批量选地点、本人确认后发布；无公众上传后台。
- 照片API日志经本地整理，由本人按需投递已有Cloud Log Check。正常报告来自AWS，受控故障及格式示例来自本地；不是实时采集。
- 工具示例/证据、个人简介与联系方式已上线，正式履歴書和職務経歴書可由获邀访客下载。
- 本轮静态更新已有针对性线上核对和本人真实手机正常反馈。未验证百万图片导入或大规模负载。
- 首页打印按钮已撤下。个人资料和正式PDF已发布并核对，新PDF无邀请/过期邀请及S3匿名直连均拒绝访问。

## 代码入口

界面修订（本地，待发布）：首页以“了解我”和“了解我的项目”为两条主入口；个人经历与正式PDF从首页进入，照片体验独立保留自然风格。原有架构图移至architecture.html，由首页顶部导航和独立横条直达。网页个人摘要聚焦运维和AWS；正式履历文件沿用已确认版本。

对外文案已按招聘方的阅读场景统一整理为三语：个人经历与项目分工采用作者视角，具体测试条件集中在技术说明及验证记录中；内部学习提醒保留在本地项目记录。

架构页现包含本机照片准备与发布、访客读取两条流程。AWS服务节点使用官方架构图标；选用的原始SVG及来源记录保存在dist/assets/aws-icons/，本机Python、Node.js和AWS CLI明确放在维护者电脑区域。

首页、架构、日志报告、工具示例与邀请入口共用深蓝/橙色主题，相册单独保留自然风格。公共邀请入口使用invite/theme.css中的同内容配色副本，避免在邀请验证前依赖受保护的根路径样式。

| 位置 | 内容 |
| --- | --- |
| [dist](dist) | HTML/CSS/JavaScript、三语文字与既有WebP展示副本 |
| [dist/architecture.html](dist/architecture.html) | 三语的本机准备/发布、访客读取流程及AWS服务架构图 |
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
    Copy-Item dist/documents.js dist/documents.private.js

contact.private.js由.gitignore排除。需要显示联系方式时，仅在该本地文件填写；保持空值则不显示联系方式。该文件供受邀请保护的网站部署使用，不提交到源码仓库。

documents.js为公开的空白默认配置。个人履历PDF放在dist/documents/，路径填写在documents.private.js，两者由.gitignore排除；空配置不显示下载按钮。发布检查会读取部署配置，并拒绝缺失文件或不安全路径。这样公开克隆可以用空白配置运行，实际受邀网站可以提供正式材料。

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

- Cloud Log Check沿用既有独立检查项目。本仓库包含照片日志整理、交接校验和报告展示，未包含其完整检查Lambda与Terraform；不把独立仓库公开作为本站交付条件。
- [运维辅助工具](https://github.com/Colin-Jiang976/my-work-tools)：原有版本、审阅版与虚构演示。
- [Java / LeetCode](https://github.com/Colin-Jiang976/leetcode-java)：独立学习记录。

通过仓库链接直接查阅，不安排邮件索取。仓库可见性由本人在GitHub决定。

## 源码与运行资料

仓库包含代码、说明和分享用示例。网站联系邮箱和电话放在被忽略的dist/contact.private.js，不硬编码进HTML/应用脚本；公开仓库只提供空白contact.example.js。.local/保存本机密钥、完整邀请、原JPG/批次、回执和原始验证资料，由.gitignore排除，不属于源码提交。首页WebP和脱敏报告JSON是明确的展示资产。网站邀请访问和GitHub仓库可见性分别管理。
