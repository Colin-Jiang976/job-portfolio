"""本人确认后发布一个本地新增批次；仅固定S3对象及目录条目，不创建资源/修改权限。"""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import prepare_photos as core
from photo_locations import clean_location, location_record

TARGET = core.LOCAL / "photo-app/publish-target.json"
PUBLISHED = core.LOCAL / "photo-app/published-catalog.json"
STATE = core.LOCAL / "photo-app/published-state.json"
FIELDS = {"PK", "SK", "id", "title", "previewKey", "originalKey", "filename", "sizeBytes", "sha256", "location"}


class PublishError(ValueError):
    pass


class AwsError(PublishError):
    def __init__(self, code, action):
        self.code = code
        super().__init__(f"AWS {action} 未完成（{code}）。保留本批后可重试；不会自动扩大权限。")


def atomic_json(path, data):
    path = Path(path).resolve()
    if not path.is_relative_to(core.LOCAL.resolve()):
        raise PublishError("记录路径必须在项目 .local 内。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    core.write_json(temporary, data)
    temporary.replace(path)


def marshal(item):
    def value(data):
        if isinstance(data, str):
            return {"S": data}
        if type(data) is int:
            return {"N": str(data)}
        if isinstance(data, dict):
            return {"M": {key: value(text) for key, text in data.items()}}
        raise PublishError("目录资料类型无效。")
    return {key: value(data) for key, data in item.items()}


def load_target(path=TARGET):
    target = core.read_json(path)
    if (target.get("profile") != "photo-maintenance" or target.get("region") != "ap-northeast-1"
            or target.get("bucket") != "cj-job-portfolio-20261024-resume" or target.get("table") != "cj-photo-catalog"
            or not re.fullmatch(r"\d{12}", target.get("account", ""))
            or target.get("principalArn") != f"arn:aws:iam::{target['account']}:user/clc-admin"):
        raise PublishError("发布目标配置与本站约定不一致，请先核对身份和资源。")
    return target


class CliAws:
    def __init__(self, target, directory):
        self.target = target
        self.directory = directory
        self.executable = shutil.which("aws")
        if not self.executable:
            raise PublishError("未找到 AWS CLI。")

    def call(self, service, operation, request, extra=()):
        request_file = self.directory / ("request-" + uuid.uuid4().hex + ".json")
        # ASCII JSON避免Windows默认文件编码差异；不写凭证或调用shell。
        request_file.write_text(json.dumps(request, ensure_ascii=True), encoding="ascii")
        parameters = ["--cli-input-json", "file://" + str(request_file)]
        if service == "s3api" and operation == "get-object":
            # CLI的文件下载命令单独处理输出参数；显式传入必填字段。
            parameters = ["--bucket", request["Bucket"], "--key", request["Key"],
                          "--expected-bucket-owner", request["ExpectedBucketOwner"]]
            if "Range" in request:
                parameters += ["--range", request["Range"]]
        command = [self.executable, service, operation, "--profile", self.target["profile"],
                   "--region", self.target["region"], "--output", "json", "--no-cli-pager", "--no-paginate",
                   "--cli-connect-timeout", "10", "--cli-read-timeout", "90",
                   *parameters, *map(str, extra)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=300)
        except subprocess.TimeoutExpired as error:
            raise AwsError("TIMEOUT", service + " " + operation) from error
        finally:
            request_file.unlink(missing_ok=True)
        if result.returncode:
            match = re.search(r"\(([A-Za-z0-9_.-]+)\)", result.stderr)
            code = match[1] if match else "CLI_ERROR"
            if code == "TransactionCanceledException":
                if "ProvisionedThroughputExceeded" in result.stderr or "ThrottlingError" in result.stderr:
                    code = "ProvisionedThroughputExceededException"
                elif "TransactionConflict" in result.stderr:
                    code = "TransactionConflict"
            if "expired" in result.stderr.lower() or "credentials" in result.stderr.lower():
                code += "，请用菜单4重新登录"
            raise AwsError(code, service + " " + operation)
        return json.loads(result.stdout or "{}")


def make_plan(batch, *, baseline_path=PUBLISHED, target_path=TARGET):
    batch = Path(batch).resolve(strict=True)
    if not batch.is_relative_to(core.LOCAL.resolve()):
        raise PublishError("批次必须位于项目 .local 内。")
    if (batch / "location-finalizing.json").exists():
        raise PublishError("地点资料尚未完成，请在菜单3重开分组页面保存后再发布。")
    catalog = core.load_baseline(batch / "catalog.json")
    if not catalog or any(set(item) - FIELDS for item in catalog):
        raise PublishError("目录为空或包含不支持字段。")
    current = core.load_baseline(baseline_path)
    known = {item["id"]: item for item in current}
    for item in catalog:
        if item["id"] in known and ({key: value for key, value in known[item["id"]].items() if key != "location"}
                                     != {key: value for key, value in item.items() if key != "location"}):
            raise PublishError("本批与已发布记录冲突，不支持在此入口替换旧照片/资料。")
    new = [item for item in catalog if item["id"] not in known]
    if not new:
        return {"batch": batch, "items": [], "alreadyPublished": len(catalog)}
    if any(not clean_location(item.get("location")) or item.get("location") in ("未分类", "未分類", "unassigned") for item in new):
        raise PublishError("新增照片必须填写拍摄地点；请用菜单2选择地点并重新准备，本次未调用AWS。")
    if len(new) != len(catalog) or core.read_json(batch / "baseline-before.json") != current:
        raise PublishError("本批的准备基准已过时，请基于当前已发布记录重新生成。")
    merged = sorted(current + new, key=lambda item: item["SK"])
    if (len({core.order_of(item) for item in merged}) != len(merged)
            or len({item["sha256"] for item in merged}) != len(merged)
            or len({item["previewKey"].lower() for item in merged}) != len(merged)):
        raise PublishError("本批与已发布记录的顺序、内容或预览键冲突。")
    if any(item["id"] != "p-" + item["sha256"][:24]
           or item["previewKey"] != f"assets/photos/{item['id']}.webp" for item in new):
        raise PublishError("统一发布仅接受维护入口自动生成的新照片ID和预览键。")
    if core.read_json(batch / "baseline-after.json") != merged:
        raise PublishError("候选发布快照与本批不一致。")
    manifest = core.read_json(batch / "manifest.json")
    if (manifest.get("status") != "prepared-local-only" or manifest.get("tableName") != "cj-photo-catalog"
            or manifest.get("albumId") != "main" or manifest.get("selectedCount") != len(new)):
        raise PublishError("发布清单无效。")
    expected = {key for item in new for key in (item["previewKey"], item["originalKey"])}
    entries = manifest["s3Files"]
    if len(entries) != len(expected) or {entry["key"] for entry in entries} != expected:
        raise PublishError("图片清单与目录路径不一致。")
    original_by_key = {item["originalKey"]: item for item in new}
    for entry in entries:
        file = (batch / "s3" / entry["key"]).resolve(strict=True)
        if not file.is_relative_to((batch / "s3").resolve()):
            raise PublishError("图片路径超出本批。")
        if file.stat().st_size != entry["sizeBytes"] or core.digest(file) != entry["sha256"]:
            raise PublishError("准备材料已变化，请重新准备。")
        if entry["sizeBytes"] > 5_000_000_000:
            raise PublishError("此入口仅支持小于5GB的单个照片文件。")
        if entry["key"] in original_by_key:
            item = original_by_key[entry["key"]]
            if item["sha256"] != entry["sha256"] or item["sizeBytes"] != entry["sizeBytes"]:
                raise PublishError("原图与目录哈希/大小不一致。")
    return {"batch": batch, "items": new, "baseline": current, "merged": merged,
            "baselinePath": Path(baseline_path).resolve(), "baselineHash": core.digest(baseline_path),
            "files": entries, "target": load_target(target_path), "alreadyPublished": 0}


def get_item(aws, target, item):
    return aws.call("dynamodb", "get-item", {"TableName": target["table"],
        "Key": marshal({"PK": item["PK"], "SK": item["SK"]}), "ConsistentRead": True}).get("Item")


def check_object(aws, target, entry, work):
    request = {"Bucket": target["bucket"], "Key": entry["key"], "ExpectedBucketOwner": target["account"]}
    try:
        head = aws.call("s3api", "head-object", {**request, "ChecksumMode": "ENABLED"})
    except AwsError as error:
        if error.code in ("404", "NotFound", "NoSuchKey"):
            return False
        raise
    if head.get("ContentLength") != entry["sizeBytes"]:
        raise PublishError("云端同名图片大小不同，拒绝覆盖：" + entry["key"])
    expected = base64.b64encode(bytes.fromhex(entry["sha256"])).decode("ascii")
    if head.get("ChecksumSHA256") == expected:
        return True
    # 控制台旧上传可能没有完整SHA256，不能把ETag或自填metadata当内容校验。
    file = work / ("readback-" + uuid.uuid4().hex)
    aws.call("s3api", "get-object", request, [file])
    if file.stat().st_size != entry["sizeBytes"] or core.digest(file) != entry["sha256"]:
        raise PublishError("云端同名图片内容不同，拒绝覆盖：" + entry["key"])
    return True


def preflight(plan, aws, work):
    target = plan["target"]
    identity = aws.call("sts", "get-caller-identity", {})
    if identity.get("Account") != target["account"] or identity.get("Arn") != target["principalArn"]:
        raise PublishError("当前AWS身份与已核对的固定身份不同，未发布。")
    table = aws.call("dynamodb", "describe-table", {"TableName": target["table"]})["Table"]
    expected_arn = f"arn:aws:dynamodb:{target['region']}:{target['account']}:table/{target['table']}"
    if table.get("TableStatus") != "ACTIVE" or table.get("TableArn") != expected_arn:
        raise PublishError("当前表状态/归属与目标不同，未发布。")
    aws.call("s3api", "head-bucket", {"Bucket": target["bucket"], "ExpectedBucketOwner": target["account"]})
    last = aws.call("dynamodb", "query", {"TableName": target["table"],
        "KeyConditionExpression": "#p = :p AND begins_with(#s, :s)",
        "ExpressionAttributeNames": {"#p": "PK", "#s": "SK"},
        "ExpressionAttributeValues": {":p": {"S": "ALBUM#main"}, ":s": {"S": "PHOTO#"}},
        "ProjectionExpression": "#p,#s", "ScanIndexForward": False, "Limit": 1, "ConsistentRead": True}).get("Items", [])
    baseline_last = max((item["SK"] for item in plan["baseline"]), default=None)
    live_last = last[0]["SK"]["S"] if last else None
    if live_last != baseline_last and live_last not in {item["SK"] for item in plan["items"]}:
        raise PublishError("云端末尾位置与本地基准/本批不同，请先同步，未发布。")
    existing_items = {}
    for item in plan["items"]:
        actual = get_item(aws, target, item)
        if actual is not None and actual != marshal(item):
            raise PublishError("云端已有不同的同键资料，拒绝覆盖：" + item["id"])
        location_row = location_record(item)
        location_actual = get_item(aws, target, location_row)
        if location_actual is not None and location_actual != marshal(location_row):
            raise PublishError("云端已有不同的地点目录，拒绝覆盖：" + item["id"])
        existing_items[item["id"]] = actual is not None and location_actual is not None
    existing_files = {entry["key"]: check_object(aws, target, entry, work) for entry in plan["files"]}
    return existing_files, existing_items


def publish(plan, confirm, *, aws=None, published_path=PUBLISHED, state_path=STATE):
    if not plan["items"]:
        return {"status": "already-recorded", "count": plan["alreadyPublished"], "awsWrites": False}
    batch = plan["batch"]
    work = batch / ("publish-check-" + uuid.uuid4().hex[:12])
    work.mkdir(exist_ok=False)
    target = plan["target"]
    aws = aws or CliAws(target, work)
    result = {"status": "checking", "batch": str(batch.relative_to(core.ROOT)),
              "uploaded": 0, "registered": 0, "reusedFiles": 0, "reusedRecords": 0,
              "awsWritesAttempted": False, "newCount": len(plan["items"])}
    receipt = batch / "publish-result.json"
    try:
        existing_files, existing_items = preflight(plan, aws, work)
        review = {"target": target, "newCount": len(plan["items"]),
                  "filesToUpload": sum(not value for value in existing_files.values()),
                  "recordsToRegister": sum(not value for value in existing_items.values())}
        if not confirm(review):
            result["status"] = "cancelled"
            atomic_json(receipt, result)
            return result
        # 确认后再核对本地基准，防止在review期间本地已被另一批推进。
        if core.digest(plan["baselinePath"]) != plan["baselineHash"]:
            raise PublishError("确认期间已发布记录发生变化，请重新准备。")
        result["status"] = "publishing"
        atomic_json(receipt, result)
        for entry in plan["files"]:
            if existing_files[entry["key"]]:
                result["reusedFiles"] += 1
                continue
            source = (batch / "s3" / entry["key"]).resolve(strict=True)
            if (not source.is_relative_to((batch / "s3").resolve()) or core.digest(source) != entry["sha256"]
                    or source.stat().st_size != entry["sizeBytes"]):
                raise PublishError("确认期间本地图片变化，尚未上传该文件。")
            request = {"Bucket": target["bucket"], "Key": entry["key"], "ExpectedBucketOwner": target["account"],
                       "IfNoneMatch": "*", "ChecksumSHA256": base64.b64encode(bytes.fromhex(entry["sha256"])).decode("ascii"),
                       "ContentType": "image/webp" if entry["key"].endswith(".webp") else "image/jpeg"}
            result["awsWritesAttempted"] = True
            try:
                aws.call("s3api", "put-object", request, ["--body", source])
            except AwsError as error:
                if error.code not in ("412", "PreconditionFailed") or not check_object(aws, target, entry, work):
                    raise
            if not check_object(aws, target, entry, work):
                raise PublishError("上传后对象未确认到位。")
            result["uploaded"] += 1
            atomic_json(receipt, result)
            print("图片已核对：" + entry["key"], flush=True)
        # 所有图片已到位之后才登记资料，避免列表先指向尚未上传的图片。
        from photo_location_maintenance import ensure_registry, register_photo
        result["awsWritesAttempted"] = True
        ensure_registry(aws, target, [item.get("location", "") for item in plan["items"]])
        for item in plan["items"]:
            if existing_items[item["id"]]:
                result["reusedRecords"] += 1
                continue
            result["awsWritesAttempted"] = True
            register_photo(aws, target, item)
            result["registered"] += 1
            atomic_json(receipt, result)
            print("目录已登记：" + item["filename"], flush=True)
        for item in plan["items"]:
            if (get_item(aws, target, item) != marshal(item)
                    or get_item(aws, target, location_record(item)) != marshal(location_record(item))):
                raise PublishError("目录写入后核对不一致，本地快照尚未推进。")
        for entry in plan["files"]:
            if not check_object(aws, target, entry, work):
                raise PublishError("最终核对时图片不存在，本地快照尚未推进。")
        if core.digest(plan["baselinePath"]) != plan["baselineHash"]:
            raise PublishError("发布期间本地基准变化，云端结果已保留，请先同步本地记录。")
        result["status"] = "verified"
        result["verifiedAt"] = datetime.now(timezone.utc).isoformat()
        atomic_json(receipt, result)
        atomic_json(published_path, plan["merged"])
        atomic_json(state_path, {"status": "published-and-read-verified", "count": len(plan["merged"]),
            "latestBatch": str(batch.relative_to(core.ROOT)), "verifiedAt": result["verifiedAt"],
            "evidence": str(receipt.relative_to(core.ROOT)), "awsWritesBy": "user-triggered maintenance tool"})
        return result
    except (PublishError, OSError, ValueError, KeyError, KeyboardInterrupt, EOFError) as error:
        result["status"] = "incomplete"
        result["error"] = str(error)
        atomic_json(receipt, result)
        raise PublishError("本批未全部完成，已完成项保留；不更新未核对的快照。结果：" + str(receipt) + "；" + str(error)) from error
