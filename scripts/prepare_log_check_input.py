"""将应用JSONL或CloudWatch CLI JSON整理为旧检查器输入；不上传AWS。"""
import argparse
import json
import re
from pathlib import Path
from log_check_common import EVENTS, MAX_BYTES, MAX_RECORDS, make_run, private_path, validate_record

PLATFORM = re.compile(r"^(?:START RequestId:|END RequestId:|REPORT RequestId:|INIT_START |INIT_REPORT )")
PREFIX = re.compile(r"^\[(?:INFO|ERROR|WARNING|WARN|DEBUG)\]\s+\S+\s+\S+\s+(.*)$", re.S)


def parse_message(value):
    """只跳过可识别的平台记录，未知或损坏的应用日志一律拒绝。"""
    if isinstance(value, str):
        value = value.strip()
        if not value or PLATFORM.match(value):
            return None
        match = PREFIX.match(value)
        if match:
            value = match[1]
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("unrecognized or malformed application log") from None
    if (isinstance(value, dict) and str(value.get("type", "")).startswith("platform.")
            and "service" not in value and "code" not in value):
        return None
    # Lambda JSON日志格式的message可为对象或JSON字符串。
    if isinstance(value, dict) and "service" not in value and "code" not in value and "message" in value:
        value = value["message"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("malformed JSON log message") from None
    validate_record(value)
    code = value.get("code")
    if (value["service"] != "cj-photo-api" or code not in EVENTS
            or (value["level"], value["message"]) != EVENTS[code]):
        raise ValueError("unexpected photo application event")
    # 只传四个固定字段；额外字段、请求ID等不进入交接输入。
    return {key: value[key] for key in ("timestamp", "level", "service", "message")}


def convert(path, input_format):
    path = private_path(path)
    if path.stat().st_size > 20 * MAX_BYTES:
        raise ValueError("raw file exceeds 20 MiB; select a smaller time range")
    raw = path.read_text(encoding="utf-8-sig")
    if input_format == "cloudwatch-json":
        wrapper = json.loads(raw)
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("events"), list):
            raise ValueError("expected AWS CLI filter-log-events JSON with events")
        # 服务分页和CLI截断的字段名不同，都不能静默丢弃后续页。
        if wrapper.get("nextToken") or wrapper.get("NextToken"):
            raise ValueError("incomplete filter-log-events result: retrieve remaining pages first")
        if "nextForwardToken" in wrapper or "nextBackwardToken" in wrapper:
            raise ValueError("get-log-events paging is not supported; use filter-log-events for a bounded time range")
        messages = []
        for row in wrapper["events"]:
            if not isinstance(row, dict) or not isinstance(row.get("message"), str):
                raise ValueError("invalid CloudWatch event")
            messages.append(row["message"])
    else:
        messages = raw.splitlines()
    records, skipped = [], 0
    for index, message in enumerate(messages, 1):
        try:
            record = parse_message(message)
        except (ValueError, TypeError) as error:
            raise ValueError(f"record {index}: {error}; nothing prepared") from None
        if record is None:
            skipped += 1
        else:
            records.append(record)
        if len(records) > MAX_RECORDS:
            raise ValueError("more than 1000 application records; select a smaller time range")
    data = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records).encode("utf-8")
    if not records or len(data) > MAX_BYTES:
        raise ValueError("input empty or exceeds 1 MiB; nothing prepared")
    return data, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--format", required=True, choices=("app-jsonl", "cloudwatch-json"))
    parser.add_argument("--source", required=True, choices=("local-api", "cloud-api", "local-controlled"))
    parser.add_argument("--scenario", required=True, choices=("normal", "read-failure"))
    args = parser.parse_args()
    try:
        data, skipped = convert(args.input, args.format)
        directory = make_run(data, source=args.source, scenario=args.scenario, raw_path=args.input, skipped=skipped)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Cannot prepare input: {error}\n")
    print(directory / "manifest.json")


if __name__ == "__main__":
    main()
