"""拍摄地点资料与排序键；由只读API和本机维护工具共同使用。"""
import hashlib
import json
import re
import unicodedata

CONFIG_KEY = "CONFIG#LOCATIONS"
UNASSIGNED = "unassigned"
LOCATION_ID = re.compile(r"(?:unassigned|loc-[a-f0-9]{24})")
PHOTO_KEY = r"PHOTO#\d{9}#[a-z0-9][a-z0-9-]{0,63}"


def clean_location(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("地点须为文字。")
    value = unicodedata.normalize("NFC", value.strip())
    if len(value) > 60 or any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("地点不能超过60字或包含控制字符。")
    return value


def location_id(label):
    label = clean_location(label)
    return "loc-" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:24] if label else UNASSIGNED


def sort_prefix(selected=""):
    if not selected:
        return "PHOTO#"
    if not isinstance(selected, str) or not LOCATION_ID.fullmatch(selected):
        raise ValueError("INVALID_LOCATION")
    return f"LOCATION#{selected}#PHOTO#"


def valid_sort_key(key, selected=""):
    prefix = f"LOCATION#{selected}#" if selected else ""
    return isinstance(key, str) and bool(re.fullmatch(re.escape(prefix) + PHOTO_KEY, key))


def location_record(item):
    if not valid_sort_key(item["SK"]):
        raise ValueError("地点记录只能从原照片目录生成。")
    return {**item, "SK": f"LOCATION#{location_id(item.get('location'))}#{item['SK']}"}


def registry(labels):
    labels = sorted({clean_location(label) for label in labels} - {""})
    if len(labels) > 200:
        raise ValueError("本版最多维护200个拍摄地点。")
    return [{"id": location_id(label), "label": label} for label in labels]


def parse_registry(value):
    if value is None:
        return []
    data = json.loads(value)
    if not isinstance(data, list) or any(not isinstance(row, dict) or set(row) != {"id", "label"} for row in data):
        raise ValueError("INVALID_LOCATIONS")
    expected = registry(row["label"] for row in data)
    if data != expected:
        raise ValueError("INVALID_LOCATIONS")
    return data


def registry_json(labels):
    return json.dumps(registry(labels), ensure_ascii=False, separators=(",", ":"))
