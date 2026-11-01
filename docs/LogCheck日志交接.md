# Log Check 本轮交接

使用说明（2026-10-26补充）：本文保存实现依据和后续步骤，不是要求本人独立完成的作业。实际操作由助手在聊天中按当前环节解释、给确切命令并核对反馈。旧dev名称现已确认clc-dev-checker；当前只执行`bash inspect_log_check_dev.sh clc-dev-checker`读取剩余信息，其余章节暂不执行。

2026-10-26：本地实现已完成，AWS未操作、旧dev未核对、页面未上传。现有三份报告为原版检查器真实本地输出。

后续进展：本人已核对旧dev、更新照片API并投递1条云端成功事件，取得AWS OK报告。展示JSON已换用该正常云端结果，另外两项仍为真实本地测试；页面尚未上传。本人在聊天中提供的报告已遮盖账号ID，导入需显式加`--account-id-redacted`，仅接受已核对dev输入桶模板中的字面量`<账户ID>`并核对唯一run路径/内容；不还原账号、不称独立核对完整账号身份。原文和此限制保存在.local的来源记录中。

照片API只读DynamoDB，并把固定INFO/ERROR事件交给现有日志组；不增加S3或SNS权限。本人取得日志、在本地整理、上传到已有检查输入桶。旧检查Lambda读取输入、保存报告、按原逻辑请求SNS。本人下载报告并脱敏，再上传网站。访客只经现有邀请读取网站文件，没有旧报告桶访问权。

## 现在本人先做的一组只读核对

东京区域的Lambda列表中，找到旧Terraform **dev** 检查函数（不是cj-photo-api）。可以在CloudShell执行：

```bash
aws lambda list-functions --region ap-northeast-1 --query 'Functions[].{Name:FunctionName,Runtime:Runtime,Handler:Handler}' --output table --no-cli-pager
```

确认函数后，把`scripts/inspect_log_check_dev.sh`上传CloudShell，执行`bash inspect_log_check_dev.sh 确切函数名`。脚本只读，显示选定函数、两个桶存在性、S3触发配置、函数调用许可、SNS订阅确认状态及照片API日志设置；不会输出邮箱或全部环境变量。遇到AccessDenied/缺变量/资源不存在，保留错误并停下，不重建、不放宽权限。

集中反馈：①dev函数名/运行时/状态；②INPUT_BUCKET、RESULTS_BUCKET是否存在且不同；③输入桶通知是否指向该函数，prefix为incoming/、suffix为.jsonl；④SNS邮箱订阅是否已确认；⑤cj-photo-api日志格式/级别。桶名和ARN可以只在本地保留，聊天中账号ID可遮盖。此查询不证明执行角色所有权限或邮件实际投递成功；后续用一次本轮输入核对真实交接。若保留旧Terraform工作目录，也可先看`terraform output resource_manifest`，不要执行apply。

## 本地工具

以下从仓库根目录执行，`python`替换为本机可用Python 3.12+路径。所有原始资料放`.local/log-check/`（Git忽略）。工具不调用AWS。

```powershell
python scripts/prepare_log_check_input.py .local/log-check/raw/photo-cloudwatch.json --format cloudwatch-json --source cloud-api --scenario normal
```

支持两种格式：①每行一个应用JSON对象（`app-jsonl`）；②AWS CLI `filter-log-events`的完整JSON，根对象含`events[].message`（`cloudwatch-json`）。支持Lambda文本前缀及JSON日志中嵌套的message；只跳过可识别的START/END/REPORT等平台记录。未知/损坏应用事件拒绝，不能截图OCR、直接粘控制台表格或静默丢弃。服务nextToken或CLI NextToken均拒绝，先完整取页；GetLogEvents的前后游标不能证明完整，首版不支持。输出四字段、最多1000条/1MiB，不静默截断；当前仅正常cloud-api、正常local-api、本地受控read-failure。

输出唯一目录，含`events.jsonl`和`manifest.json`。清单记输入SHA256、来源、场景、跳过数、唯一云端输入/报告键。不要重新用旧键，以免覆盖旧报告。`create_log_check_demo.py --checker .local/log-check/engine/check.py`可重建本地三类材料；原版check.py通过GitHub连接器取得，Git blob必须为`a2da7c96f97d67da15e270e596abaca0c62e75ff`，脚本校验后才执行；受控副本和来源记在忽略目录，没有嵌套Git仓库或改上游代码。

```powershell
python scripts/prepare_log_check_reports.py --manifest .local/log-check/RUN/manifest.json --report .local/log-check/RUN/report-local.json --engine local --output dist/log-check/reports.json
```

每条重复一组`--manifest`/`--report`；`--engine`给一个则共用，混合本地和AWS则按相同顺序每条给一个。AWS条目还需`--cloud-input-uri s3://实际输入桶/incoming/RUN/events.jsonl`，本地条目在混合批次用`--cloud-input-uri -`占位。报告必须对应当前输入、schema=1.0、时间带时区、状态/数量/原因一致。INVALID的counts和total_records必须null。默认SNS为unconfirmed，只有本人确实收到才给该条`--sns received`；本地和OK不标已收到。所有条目验证后才替换展示JSON，同时在.local保存报告路径/哈希和发布对应关系。

## 旧dev核对后再进行的交接

1. 本人更新现有cj-photo-api代码（Python3.12、lambda_function.lambda_handler不变），不改执行角色；确认INFO能观察。若云端已有JSON日志级别设置，核对其是否允许INFO，不擅自切格式或更改资源。
2. 记住开始时间，在有效邀请浏览器打开一次照片列表。CloudShell以短时间窗口取日志，下载后存到`.local/log-check/raw/`。例如（`START_MS`、`END_MS`是本人刚才窗口的Unix毫秒）：

```bash
aws logs filter-log-events --region ap-northeast-1 --log-group-name /aws/lambda/cj-photo-api --start-time "$START_MS" --end-time "$END_MS" --output json --no-cli-pager > photo-cloudwatch.json
```

不要用`--no-paginate`/`--max-items`隐藏后续记录。不要导出全部历史或把原始日志上传网站。新增INFO产生实际日志用量，不是费用硬封顶。

3. 正常云端日志转换后，按清单唯一键上传`events.jsonl`到旧输入桶。另两类已有本地受控/格式样本，可各投递一次验证旧云端检查器；来源仍保留本地受控/格式测试。不要破坏线上权限或表制造错误，不连续反复投递/发邮件。
4. 从旧报告桶**对应清单的报告键**下载原始报告到本轮目录（如`report-aws.json`）。取不到报告属于交接/技术故障，不能自行写INVALID。核对旧流程有报告后，再用`--engine aws`脱敏；输入来源和执行位置是两个字段。工具核对文件对应关系，不是数字签名认证，原件取得过程仍由本人核对。
5. 将下面文件上传现有网站私有S3：`dist/log-check/`五文件、`dist/index.html`、`dist/app.js`、`dist/content.js`及此前尚未上传的`dist/architecture.css`。`theme.css`沿用线上已有文件。**不要上传.local或原始报告**，不新增CloudFront公开行为。首页仍标旧环境未复核，待真实云端交接通过再调整事实说明。
6. 定向失效首页及上述新增/修改路径。只验本轮路径：有效邀请下页面和reports.json可读；无邀请/过期邀请两者拒绝；网站S3同路径匿名直连拒绝；三语/手机/入口正确。既有17项及全部原图不重跑。报告存在不等于SNS邮件已收到。

本轮本地失败返回503并生成ERROR，缺字段测试经旧检查器生成INVALID。原JPG走S3/CloudFront，API日志不能证明原图下载或浏览器保存成功。

实现文件：`backend/photo-api/lambda_function.py`；`scripts/*log_check*.py`；`dist/log-check/`。针对性验证：在scripts目录运行`python -m unittest -v test_log_check`；需已有本地演示原件（生成步骤见上），不连接AWS。

格式依据：[AWS Python日志](https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html)、[FilterLogEvents CLI](https://docs.aws.amazon.com/cli/latest/reference/logs/filter-log-events.html)、[S3触发配置只读查询](https://docs.aws.amazon.com/cli/latest/reference/s3api/get-bucket-notification-configuration.html)、[原版检查器](https://github.com/Colin-Jiang976/cloud-log-check/blob/master/check.py)。
