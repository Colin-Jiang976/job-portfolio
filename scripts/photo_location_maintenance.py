"""本人确认后维护既有照片的拍摄地点；只写原表的目录，不上传或删除图片。"""
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/photo-api"))
from photo_locations import (CONFIG_KEY, clean_location, location_id, location_record,
                             parse_registry, registry_json)


def registry_item(labels):
    return {"PK": "ALBUM#main", "SK": CONFIG_KEY, "locationsJson": registry_json(labels)}


def exact_condition(item, fields):
    """比较已读取的全部已知字段，防止确认后并发改动被静默覆盖。"""
    names, values, clauses = {}, {}, []
    for index, key in enumerate(sorted(fields)):
        name, value = f"#c{index}", f":c{index}"
        names[name] = key
        if key in item:
            from photo_publish import marshal
            values[value] = marshal({key: item[key]})[key]
            clauses.append(f"{name} = {value}")
        else:
            clauses.append(f"attribute_not_exists({name})")
    return {"ConditionExpression": " AND ".join(clauses), "ExpressionAttributeNames": names,
            **({"ExpressionAttributeValues": values} if values else {})}


def read_registry(aws, target):
    from photo_publish import get_item
    raw = get_item(aws, target, {"PK": "ALBUM#main", "SK": CONFIG_KEY})
    return raw, parse_registry(raw["locationsJson"]["S"] if raw else None)


def ensure_registry(aws, target, labels):
    from photo_publish import AwsError, PublishError, marshal
    for _ in range(4):
        raw, current = read_registry(aws, target)
        new = registry_item([r["label"] for r in current] + list(labels))
        if raw == marshal(new):
            return
        before = {"PK": "ALBUM#main", "SK": CONFIG_KEY}
        if raw:
            before["locationsJson"] = raw["locationsJson"]["S"]
        request = {"TableName": target["table"], "Item": marshal(new),
                   **exact_condition(before, {"locationsJson"})}
        if not raw:
            request = {"TableName": target["table"], "Item": marshal(new),
                       "ConditionExpression": "attribute_not_exists(#p)", "ExpressionAttributeNames": {"#p": "PK"}}
        try:
            aws.call("dynamodb", "put-item", request)
            return
        except AwsError as error:
            if error.code != "ConditionalCheckFailedException":
                raise
    raise PublishError("地点清单同时被修改，请重试本批。")


def transact(aws, actions):
    from photo_publish import AwsError
    token = uuid.uuid4().hex
    for attempt in range(5):
        try:
            return aws.call("dynamodb", "transact-write-items", {"TransactItems": actions, "ClientRequestToken": token})
        except AwsError as error:
            if error.code not in {"ThrottlingException", "ProvisionedThroughputExceededException",
                                  "TransactionInProgressException", "TransactionConflict"} or attempt == 4:
                raise
            time.sleep(2 ** attempt)


def register_photo(aws, target, item):
    """两个目录条目在同一事务内登记；重复运行须完全一致。"""
    from photo_publish import FIELDS, PublishError, get_item, marshal
    actions = []
    for row in (item, location_record(item)):
        raw = get_item(aws, target, row)
        if raw is not None and raw != marshal(row):
            raise PublishError("云端已有不同的目录资料，拒绝覆盖：" + item["id"])
        if raw:
            actions.append({"ConditionCheck": {"TableName": target["table"],
                "Key": marshal({"PK": row["PK"], "SK": row["SK"]}), **exact_condition(row, FIELDS)}})
        else:
            actions.append({"Put": {"TableName": target["table"], "Item": marshal(row),
                "ConditionExpression": "attribute_not_exists(#p)", "ExpressionAttributeNames": {"#p": "PK"}}})
    transact(aws, actions)


def edit_locations(assignments, confirm, *, baseline_path=None, aws=None, target_path=None):
    """先只读核对所有受影响记录；确认后逐张原子修改，并在核对后更新本地基准。"""
    import prepare_photos as core
    from photo_publish import (FIELDS, PUBLISHED, TARGET, CliAws, PublishError, atomic_json,
                               get_item, load_target, marshal)
    baseline_path = Path(baseline_path or PUBLISHED)
    current = core.load_baseline(baseline_path)
    original_hash = core.digest(baseline_path)
    if not isinstance(assignments, dict) or not assignments or set(assignments) - {p["id"] for p in current}:
        raise PublishError("地点清单须使用已发布照片ID，且不能为空。")
    assignments = {key: clean_location(value) for key, value in assignments.items()}
    target = load_target(target_path or TARGET)
    work = core.LOCAL / "photo-app/location-updates" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    aws = aws or CliAws(target, work)
    identity = aws.call("sts", "get-caller-identity", {})
    if identity.get("Account") != target["account"] or identity.get("Arn") != target["principalArn"]:
        raise PublishError("当前AWS身份与固定目标不同，未修改地点。")
    table = aws.call("dynamodb", "describe-table", {"TableName": target["table"]})["Table"]
    if (table.get("TableStatus") != "ACTIVE" or table.get("TableArn") !=
            f"arn:aws:dynamodb:{target['region']}:{target['account']}:table/{target['table']}"):
        raise PublishError("目录表状态或归属不一致，未修改地点。")
    jobs = []
    for old in current:
        if old["id"] not in assignments:
            continue
        new = {**old, "location": assignments[old["id"]]}
        actual = get_item(aws, target, old)
        # 支持上次事务已成功、但进程在保存本地快照前中断的恢复。
        if actual not in (marshal(old), marshal(new)):
            raise PublishError("云端照片资料与本地基准不一致，未覆盖：" + old["filename"])
        before = old if actual == marshal(old) else new
        new_row = location_record(new)
        old_row = location_record(before)
        actual_new = get_item(aws, target, new_row)
        if actual_new is not None and actual_new != marshal(new_row):
            raise PublishError("云端已有不同的地点目录，未覆盖：" + old["filename"])
        actual_old = get_item(aws, target, old_row) if old_row["SK"] != new_row["SK"] else None
        if actual_old is not None and actual_old != marshal(old_row):
            raise PublishError("原地点目录与照片资料不一致，未修改。")
        jobs.append((before, new, old_row if actual_old else None, actual_new))
    receipt = {"status": "checked-read-only", "assignments": assignments, "completed": [], "awsWritesAttempted": False}
    core.write_json(work / "baseline-before.json", current)
    atomic_json(work / "result.json", receipt)
    if not confirm({"target": target, "photos": [new for _, new, _, _ in jobs]}):
        receipt["status"] = "cancelled"
        atomic_json(work / "result.json", receipt)
        return receipt
    try:
        if core.digest(baseline_path) != original_hash:
            raise PublishError("确认期间本地已发布记录发生变化，请重新核对。")
        receipt["awsWritesAttempted"] = True
        ensure_registry(aws, target, assignments.values())
        for before, new, old_row, actual_new in jobs:
            new_row = location_record(new)
            actions = [{"Put": {"TableName": target["table"], "Item": marshal(new),
                                  **exact_condition(before, FIELDS)}}]
            if actual_new:
                actions.append({"ConditionCheck": {"TableName": target["table"],
                    "Key": marshal({"PK": new_row["PK"], "SK": new_row["SK"]}), **exact_condition(new_row, FIELDS)}})
            else:
                actions.append({"Put": {"TableName": target["table"], "Item": marshal(new_row),
                    "ConditionExpression": "attribute_not_exists(#p)", "ExpressionAttributeNames": {"#p": "PK"}}})
            if old_row:
                actions.append({"Delete": {"TableName": target["table"],
                    "Key": marshal({"PK": old_row["PK"], "SK": old_row["SK"]}), **exact_condition(old_row, FIELDS)}})
            transact(aws, actions)
            if get_item(aws, target, new) != marshal(new) or get_item(aws, target, new_row) != marshal(new_row):
                raise PublishError("地点写入后的目录核对不一致。")
            if old_row and get_item(aws, target, old_row) is not None:
                raise PublishError("旧地点目录尚未移除。")
            receipt["completed"].append(new["id"])
            atomic_json(work / "result.json", receipt)
            print("地点已核对：" + new["filename"] + " → " + (new["location"] or "未分类"), flush=True)
        if core.digest(baseline_path) != original_hash:
            raise PublishError("更新期间本地已发布记录发生变化，云端结果保留，请同步后再继续。")
        updated = {new["id"]: new for _, new, _, _ in jobs}
        atomic_json(baseline_path, [updated.get(item["id"], item) for item in current])
        receipt["status"] = "verified"
        receipt["evidence"] = str(work / "result.json")
        atomic_json(work / "result.json", receipt)
        return receipt
    except (ValueError, OSError, KeyError, KeyboardInterrupt, EOFError) as error:
        receipt.update(status="incomplete", error=str(error))
        atomic_json(work / "result.json", receipt)
        raise PublishError("地点维护未全部完成，可重试相同清单；记录：" + str(work / "result.json") + "；" + str(error)) from error
