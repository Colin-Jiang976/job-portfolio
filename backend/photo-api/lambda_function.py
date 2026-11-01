"""照片目录 API（Python 3.12）。只读资料，不读取或转发 JPG 文件。"""

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from photo_locations import (CONFIG_KEY, UNASSIGNED, clean_location, location_id,
                             parse_registry, sort_prefix, valid_sort_key)

PAGE_SIZE = 24
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
SORT_KEY = re.compile(r"PHOTO#\d{9}#[a-z0-9][a-z0-9-]{0,63}")
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
_client = None


def application_event(level, code):
    """只记录固定应用事件；不带请求、凭证、照片资料或原始异常。"""
    messages = {"PHOTO_LIST_READ_OK": "Photo catalog page read successfully",
                "PHOTO_READ_FAILED": "Photo catalog read failed"}
    LOGGER.log(level, json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                "level": logging.getLevelName(level), "service": "cj-photo-api",
                                "message": messages[code], "code": code}, separators=(",", ":")))


def encode_cursor(key):
    """把上一页末尾的位置做成书签，不在书签里保存凭据。"""
    if key is None:
        return None
    raw = json.dumps(key, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token, partition, selected=""):
    if not token:
        return None
    if len(token) > 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("INVALID_CURSOR")
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        key = json.loads(raw)
        if (not isinstance(key, dict) or set(key) != {"PK", "SK"}
                or key["PK"] != partition or not isinstance(key["SK"], str)
                or not valid_sort_key(key["SK"], selected)):
            raise ValueError()
        return key
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("INVALID_CURSOR") from error


def optional_title(value):
    """标题可省略、用一段文字，或只提供需要的语言；不自动翻译。"""
    def clean(text):
        if not isinstance(text, str) or len(text) > 300:
            raise ValueError("INVALID_TITLE")
        return text.strip()

    if value is None:
        return None
    if isinstance(value, str):
        return clean(value) or None
    if isinstance(value, dict):
        result = {lang: clean(value[lang]) for lang in ("ja", "zh", "en") if lang in value}
        return {lang: text for lang, text in result.items() if text} or None
    raise ValueError("INVALID_TITLE")


def public_photo(item, album_id):
    """核对资料，只返回网页需要的字段；缺少标题是正常情况。"""
    photo_id = item.get("id")
    filename = item.get("filename")
    size = item.get("sizeBytes")
    preview = item.get("previewKey")
    original = item.get("originalKey")
    checksum = item.get("sha256")
    if (not isinstance(photo_id, str) or not ID.fullmatch(photo_id)
            or type(size) is not int or not 0 < size <= 2**53 - 1
            or not isinstance(filename, str) or not re.fullmatch(r"[^/\\\x00-\x1f]+\.jpe?g", filename, re.I)
            or not isinstance(preview, str) or not re.fullmatch(r"assets/photos/[A-Za-z0-9_.-]+\.webp", preview)
            or original != f"photo-originals/{album_id}/{photo_id}.jpg"
            or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum)):
        raise ValueError("INVALID_PHOTO_RECORD")
    photo = {"id": photo_id, "filename": filename, "sizeBytes": size, "sha256": checksum,
             "previewUrl": "/" + preview, "downloadUrl": "/" + original}
    title = optional_title(item.get("title"))
    if title is not None:
        photo["title"] = title
    if "location" in item:
        if not isinstance(item["location"], str):
            raise ValueError("INVALID_LOCATION")
        photo["location"] = clean_location(item["location"])
    return photo


def handle_request(event, read_page, album_id="main", read_locations=None):
    """一次请求：检查输入 → 读取一页 → 整理照片资料 → 返回结果。"""
    method = event.get("requestContext", {}).get("http", {}).get("method")

    def respond(status, data, **headers):
        return {"statusCode": status,
                "headers": {"content-type": "application/json; charset=utf-8",
                            "cache-control": "private, no-store", "x-content-type-options": "nosniff", **headers},
                "body": "" if method == "HEAD" else json.dumps(data, ensure_ascii=False, allow_nan=False)}

    if event.get("rawPath") != "/api/photos":
        return respond(404, {"code": "NOT_FOUND"})
    if method not in ("GET", "HEAD"):
        return respond(405, {"code": "METHOD_NOT_ALLOWED"}, allow="GET, HEAD")
    if not isinstance(album_id, str) or not ID.fullmatch(album_id):
        application_event(logging.ERROR, "PHOTO_READ_FAILED")
        return respond(503, {"code": "PHOTO_SERVICE_UNAVAILABLE"})
    partition = f"ALBUM#{album_id}"
    params = parse_qsl(event.get("rawQueryString") or "", keep_blank_values=True)
    if any(key not in ("cursor", "location") for key, _ in params) or len({k for k, _ in params}) != len(params):
        return respond(400, {"code": "INVALID_REQUEST"})
    params = dict(params)
    selected = params.get("location", "")
    try:
        prefix = sort_prefix(selected)
    except ValueError:
        return respond(400, {"code": "INVALID_LOCATION"})
    try:
        after = decode_cursor(params.get("cursor"), partition, selected)
    except ValueError:
        return respond(400, {"code": "INVALID_CURSOR"})
    try:
        page = read_page(partition=partition, after=after, limit=PAGE_SIZE,
                         **({"prefix": prefix} if selected else {}))
        items = page["items"]
        if not isinstance(items, list) or len(items) > PAGE_SIZE:
            raise ValueError("INVALID_PAGE")
        photos = [public_photo(item, album_id) for item in items]
        if selected and any(location_id(item.get("location")) != selected for item in items):
            raise ValueError("WRONG_LOCATION_RECORD")
        last_key = page.get("lastKey")
        if last_key is not None:
            decode_cursor(encode_cursor(last_key), partition, selected)
        data = {"photos": photos, "nextCursor": encode_cursor(last_key)}
        if read_locations is not None:
            data["locations"] = read_locations(partition)
            data["selectedLocation"] = selected
        response = respond(200, data)
        application_event(logging.INFO, "PHOTO_LIST_READ_OK")
        return response
    except Exception:
        application_event(logging.ERROR, "PHOTO_READ_FAILED")
        return respond(503, {"code": "PHOTO_SERVICE_UNAVAILABLE"})


def from_dynamo(item):
    """拆除 DynamoDB 的类型标记，保留普通 Python 字符串和整数。"""
    photo = {name: item.get(name, {}).get("S")
             for name in ("id", "previewKey", "originalKey", "filename", "sha256")}
    photo["sizeBytes"] = int(item["sizeBytes"]["N"])
    title = item.get("title", {})
    if "S" in title:
        photo["title"] = title["S"]
    elif "M" in title:
        photo["title"] = {lang: value.get("S") for lang, value in title["M"].items()}
    elif title.get("NULL") is True:
        pass
    elif title:
        raise ValueError("INVALID_TITLE")
    if "location" in item:
        if not isinstance(item["location"].get("S"), str):
            raise ValueError("INVALID_LOCATION")
        photo["location"] = clean_location(item["location"]["S"])
    return photo


def lambda_handler(event, context):
    """AWS 执行入口。表名、相册来自环境变量，权限来自执行角色。"""
    table_name = os.environ.get("PHOTO_TABLE")
    album_id = os.environ.get("PHOTO_ALBUM", "main")

    def client():
        global _client
        if not table_name:
            raise ValueError("PHOTO_TABLE_NOT_CONFIGURED")
        if _client is None:
            import boto3  # Lambda Python 运行时提供；本地模拟不需要 AWS 连接。
            _client = boto3.client("dynamodb")
        return _client

    def read_locations(partition):
        result = client().query(TableName=table_name,
            KeyConditionExpression="#p = :p AND #s = :s",
            ExpressionAttributeNames={"#p": "PK", "#s": "SK", "#j": "locationsJson"},
            ExpressionAttributeValues={":p": {"S": partition}, ":s": {"S": CONFIG_KEY}},
            ProjectionExpression="#j", Limit=1, ConsistentRead=True)
        rows = result.get("Items", [])
        return parse_registry(rows[0]["locationsJson"]["S"] if rows else None)

    def read_page(*, partition, after, limit, prefix="PHOTO#"):
        request = {
            "TableName": table_name,
            "KeyConditionExpression": "#pk = :album AND begins_with(#sk, :photo)",
            "ExpressionAttributeNames": {"#pk": "PK", "#sk": "SK", "#id": "id", "#preview": "previewKey",
                                         "#original": "originalKey", "#file": "filename", "#bytes": "sizeBytes",
                                         "#hash": "sha256", "#title": "title", "#location": "location"},
            "ExpressionAttributeValues": {":album": {"S": partition}, ":photo": {"S": prefix}},
            "ProjectionExpression": "#id, #preview, #original, #file, #bytes, #hash, #title, #location",
            "Limit": limit,
            "ConsistentRead": True,
        }
        if after:
            request["ExclusiveStartKey"] = {key: {"S": value} for key, value in after.items()}
        result = client().query(**request)
        last = result.get("LastEvaluatedKey")
        return {"items": [from_dynamo(item) for item in result.get("Items", [])],
                "lastKey": {key: value["S"] for key, value in last.items()} if last else None}

    return handle_request(event, read_page, album_id, read_locations)
