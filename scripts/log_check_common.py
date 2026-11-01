"""Log Check 本地交接的格式校验；只用 Python 标准库。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/log-check"
MAX_BYTES, MAX_RECORDS = 1048576, 1000
EVENTS = {"PHOTO_LIST_READ_OK": ("INFO", "Photo catalog page read successfully"),
          "PHOTO_READ_FAILED": ("ERROR", "Photo catalog read failed")}
SOURCES = {"local-api", "cloud-api", "local-controlled", "format-test"}
SCENARIOS = {"normal", "read-failure", "invalid-format"}


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str) or "T" not in value or len(value) > 64:
        raise ValueError("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise ValueError("invalid timestamp") from None
    return value


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(LOCAL.resolve()):
        raise ValueError("raw materials must stay under .local/log-check")
    return path


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("expected JSON object")
    timestamp(record.get("timestamp"))
    if record.get("level") not in ("INFO", "WARN", "ERROR"):
        raise ValueError("invalid level")
    for key in ("service", "message"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError("invalid " + key)
    return record


def inspect_input(data):
    """独立复核实际交接文件，避免只信可编辑清单。INVALID不保留部分计数。"""
    if len(data) > MAX_BYTES:
        return "INVALID", None, "size"
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "INVALID", None, "encoding"
    counts = dict.fromkeys(("INFO", "WARN", "ERROR"), 0)
    for line in content.splitlines():
        if not line.strip():
            continue
        if sum(counts.values()) >= MAX_RECORDS:
            return "INVALID", None, "records"
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return "INVALID", None, "json"
        try:
            validate_record(record)
        except ValueError:
            return "INVALID", None, "fields"
        counts[record["level"]] += 1
    if not sum(counts.values()):
        return "INVALID", None, "empty"
    return ("ALERT" if counts["ERROR"] else "OK"), counts, None


def make_run(data, *, source, scenario, raw_path=None, skipped=0):
    if (source not in SOURCES or scenario not in SCENARIOS
            or (scenario == "normal" and source not in {"local-api", "cloud-api"})
            or (scenario == "read-failure" and source != "local-controlled")
            or (scenario == "invalid-format" and source != "format-test")):
        raise ValueError("invalid source/scenario pair")
    status, counts, reason = inspect_input(data)
    expected = {"normal": "OK", "read-failure": "ALERT", "invalid-format": "INVALID"}[scenario]
    if status != expected:
        raise ValueError("input does not match scenario")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
    directory = LOCAL / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "events.jsonl").write_bytes(data)
    manifest = {"schema_version": "1.0", "run_id": run_id, "created_at": now(),
                "source": source, "scenario": scenario, "input_sha256": sha(data),
                "input_file": "events.jsonl", "expected_status": status, "counts": counts,
                "reason_category": reason, "skipped_platform_records": skipped,
                "cloud_input_key": f"incoming/{run_id}/events.jsonl",
                "cloud_report_key": f"reports/{run_id}/events.json"}
    if raw_path is not None:
        path = private_path(raw_path)
        manifest.update(raw_file=str(path), raw_sha256=sha(path.read_bytes()))
    write_json(directory / "manifest.json", manifest)
    return directory


def reason_category(reason):
    if not isinstance(reason, str):
        raise ValueError("missing INVALID reason")
    fixed = {"file exceeds 1 MiB": "size", "file exceeds 1000 records": "records",
             "file must be UTF-8": "encoding", "file contains no records": "empty"}
    if reason in fixed:
        return fixed[reason]
    if re.fullmatch(r"invalid JSON at line [1-9][0-9]*", reason):
        return "json"
    if re.fullmatch(r"(?:expected JSON object|missing or invalid (?:level|service|message|timestamp)) at line [1-9][0-9]*", reason):
        return "fields"
    raise ValueError("unrecognized INVALID reason")
