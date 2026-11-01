# 下一对话交接：照片阶段完成，继续项目框架

更新：2026-11-01（日本时间）。本人明确要求先整理交接，由本人另开对话；不要自动建聊天、提交或推送。本文件覆盖历史“类别未做/9张/待上传/收集履历”的下一步安排。

## 最新决定与下一主线

照片维护、地点筛选及新增83张发布已完成，线上共92张。本人最后发现：拍摄地点选项使用自己填写的中文，切换日文/英文界面时仍是中文。本人明确：这项改动若范围不大，先不改，留到项目最后整体三语修订。助手核对源码后判断可以限定为地点显示翻译，不需重传图片或改变分类；本轮没有实现或发布翻译补丁。

接下来回原四周计划的项目框架，按本人新对话具体要求推进。剩余候选为作品示例/证据的访客入口、可配置的履历文件下载框架，最后集中处理手机/三语/入口/源码查阅。本人没有现成履历，个人信息和正式文件后补，不能以收集任职资料阻塞框架。联系方式已上线，不要再加一次。整体讲解练习留项目完成后，不插入课程或考试。

接续先读AGENTS.md、JOB_SEARCH_SITE_BLUEPRINT.md及PROJECT_STATUS.md最上方，再按任务读CAREER_DEVELOPMENT_PLAN.md、本文对应源码和证据；不反复全量读取历史、重做职业复盘或扩大四周范围。

## 照片实际完成状态

- 原9张＋新增83张＝线上92张。新增原JPG共1,200,792,171字节，上传166个图片文件（83原JPG＋83 WebP），登记83张照片，另有地点查询目录副本；不是只写83个DynamoDB item。
- 九地点：富士山18、伊豆21、东京6、箱根13、内蒙古14、逗子4、横滨3、小田原7、热海6。
- 总列表真实分页24／24／24／20，无遗漏重复；九地精确集合、资料/原路径、一张新预览及新原图64字节Range请求均通过。单地点都少于24；地点内多页24／24／5来自明确合成资料，不能混称真实验收。
- 几百万张仍为扩展目标，尚未实现/验证百万级导入或负载。现有单维护者CLI、完整本地快照、单相册PK及限流不能用92张成功代替规模验证，不自动加入公众上传、压测或新资源。
- 本人觉得发布慢，一度以为卡死，但此前明确先不做速度优化。约1.20GB、166文件及逐项CLI核对为实际流程，未测各阶段耗时，不编造网络/CLI占比，不另开优化任务。

## 维护者操作与代码职责

固定入口job-portfolio/Photo-Maintenance.cmd，直接启动Python，不依赖放宽PowerShell执行策略。

1. 新JPG复制到.local/photo-app/new-input，已发布原图按哈希跳过，不要求删旧输入。
2. 菜单2：生成新图预览/原JPG副本/资料，再打开本地看图页面。多选同地照片一次应用地点，可添加地点、保存未完成进度；地点齐全后“保存地点并完成准备”。
3. 菜单3：继续最近未发布批次看图分组；已发布批次则打开材料，不重打包。
4. 菜单4：临时会话过期才aws login并STS核对；profile photo-maintenance、东京、固定身份clc-admin，不建长期Key/改IAM。官方可选AI skills/MCP提示曾选n，不是自写安装。
5. 菜单5：只读核对身份/目标/文件/冲突，显示计划；本人PUBLISH确认后才上传S3、登记DynamoDB。中断留回执，同批可重试；新增缺地点或资料正在更新时拒绝发布。
6. 菜单6/7仅修改旧照片地点：本地看图保存→本人LOCATIONS确认写表。正常新图不需再6/7补登记。

源码分工：

- scripts/photo_maintenance.py：菜单和调度。
- prepare_photos.py、prepare-photo-data.cjs：预览/原图副本、ID/排序、大小/哈希、JSON与拆批；Node仍在使用，不笼统说只有三个Python工具。
- photo_location_picker.py及photo-location-picker/：仅本机HTTP、HTML/CSS/JavaScript看图多选、保存清单，不识图猜地点或调用AWS。
- photo_new_batch.py：地点齐全后同步本批catalog、选择清单、导入资料、候选基准，复用已生成图片。
- photo_publish.py：CLI、确认发布、核对、回执/本地快照。
- photo_location_maintenance.py：地点元数据、条件事务。
- backend/photo-api/lambda_function.py和photo_locations.py：只读API、地点校验、Query与分页。

本地页面的随机会话地址/进程不是永久入口。旧8776用于已发布9张，8777用于本批83张；新对话不依赖旧进程，必要时用CMD重新开，不让本人重分92张。

## AWS数据与权限

访客：签名Cookie→CloudFront→Lambda/DynamoDB取目录；图片经CloudFront/S3交付，不经Lambda转发。维护者：CMD/Python→CLI/本人临时IAM身份→S3及DynamoDB，两种授权不同。邀请由本地签发、CloudFront校验，没有邀请Lambda。

资源：S3 cj-job-portfolio-20261024-resume、CloudFront E1EXJ282JJY07Q（dh0h1qa1vbzc5.cloudfront.net）、Python3.12 Lambda cj-photo-api（lambda_function.lambda_handler）、DynamoDB cj-photo-catalog，均沿用。

原目录PK=ALBUM#main、SK=PHOTO#顺序#ID；同表同PK另有SK=LOCATION#地点ID#PHOTO#顺序#ID副本，复用原图片路径。地点选项在CONFIG#LOCATIONS。API按排序键前缀Query，非Scan、FilterExpression或只筛当前24条；书签绑定地点。事务同步原目录和地点副本，改地只移除旧查询条目，不删除S3图片。

未新建表/GSI或扩大Lambda权限，沿用同表同相册Query；发布使用本人已有IAM身份。原权限、费用提醒和限流不重配，提醒不是费用硬封顶。

## 已知待整体修正：地点名称三语

相册按钮/状态已有日中英，但API的locations[].label是维护者输入原文，dist/photos/app.js直接显示，故九地名称为中文。这是实际待修项，不能记作三语全部完成。

建议保留现有地点ID、查询参数、照片归类，按界面语言显示译名。现有九地可用显示映射做小范围修改，未知新地点回退原文；若扩展地点元数据多语字段，则须兼容photo_locations.py的parse_registry及前端校验，不直接改变接口结构。

特别注意：地点ID由规范化原始地点文字的SHA256前24位生成，不能将已存location直接改为日/英文再重算ID，否则查询键改变。翻译不需重传原图、重分92张、重建数据库或增加人工三语照片标题。具体实现留最后整体修订时确定，本轮不做。

## 证据与说明索引

以下路径均相对job-portfolio/：

- 最新批次.local/photo-app/batches/20261101-112642-34c2e3f8/；其publish-result.json为verified/166文件/83张。
- .local/photo-app/published-catalog.json及published-state.json均92。
- 本批线上15项：上述批次/online-verification-20261101-030604/results.json。
- 首轮地点上线19项：.local/photo-app/location-feature-check/online-verification-20261101-013034/results.json。
- 静态已发布基准.local/site-releases/published-reference.json指向release-20261030-215539-9487211e，范围photos四文件；未变首页沿用此前联系更新证据。
- docs/照片维护设计说明.md、照片地点筛选.md、照片批量维护.md保存流程；docs/网站更新与恢复.md保存静态更新/本地恢复。
- 针对性检查分多轮且有重叠，不把计数相加，不重跑原17项、重下载全部原图或制造新上传验收。

## 原计划剩余与接续边界

Log Check按需交接、来源明确的脱敏三语报告、首页架构图、Java入口已上线；受控故障/格式结果标本地，不是实时采集。MonitorTool/RdsLogArchive本地审阅、必要修正、虚构演示与本人反馈已完成；网站有说明，访客演示/证据入口仍缺，不能把本地演示说成已接网页。

Site-Release.cmd及检查/增量包/本地静态恢复完成，不是云端全栈或照片库/数据库灾难恢复。联系方式已上线验证。履历下载框架未做，本人无现成文件，个人资料后补；不放假下载链接或假履历。源码给招聘方的查阅方式及最终集中体验检查待收尾，不自动公开私有仓库。

代码仓库是job-portfolio/，上级规划根目录不是Git仓库。大量既有已修改/未跟踪源码尚未提交，保留全部及dist/content.js原roleValue三语试改，不重置或擅自推送。密钥、完整邀请、私人原JPG、生成批次/回执继续排除在Git外，不公开.local。

本人为新人，目标展现AWS理解，代码由AI协助，不夸大独立实现、节时或百万规模。后期解说围绕需求→取舍→数据/权限链→本人操作→验证依据，按源码/回执/历史聊天找事实；不承诺跨聊天逐字记忆，也不要求本人现在把问题全部问完。

每次回复末尾给具体下一步、执行人和需反馈内容。按完整环节推进，助手自主定位/实现/必要检查，AWS本人操作；不逐菜单确认、做美化/外围工具或旧验收。四周至11/22、11月底SAA目标/12月求职保持，12月前不另开Linux课程。

建议新对话起始语：

> 请按NEXT_CHAT_HANDOFF.md继续完成项目框架。照片92张及地点筛选已完成，地点名称日英显示留最后整体修订。先核对剩余作品演示/证据入口和履历下载框架；个人资料后补，不重跑照片验收或另扩功能。
