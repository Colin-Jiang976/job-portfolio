"""以同一API和有来源的原版check.py生成三类真实本地演示；不访问AWS。"""
import argparse
import hashlib
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
from log_check_common import LOCAL, ROOT, make_run, sha, write_json
from prepare_log_check_input import convert
from prepare_log_check_reports import sanitize

sys.path.insert(0, str(ROOT / "backend/photo-api"))
import lambda_function as api

CHECK_BLOB = "a2da7c96f97d67da15e270e596abaca0c62e75ff"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def generate(checker):
    checker = Path(checker).resolve()
    if not checker.is_relative_to(LOCAL.resolve()):
        raise ValueError("keep controlled checker copy under .local/log-check")
    data = checker.read_bytes()
    if git_blob(data) != CHECK_BLOB:
        raise ValueError("checker differs from reviewed upstream blob")
    write_json(checker.parent / "SOURCE.json", {
        "repository": "https://github.com/Colin-Jiang976/cloud-log-check",
        "file": "check.py", "ref_at_fetch": "master", "git_blob": CHECK_BLOB,
        "sha256": sha(data), "note": "Read-only GitHub connector copy; original code unchanged. No nested Git repository."})
    catalog = json.loads((ROOT / ".local/photo-app/catalog.json").read_text(encoding="utf-8-sig"))
    event = {"rawPath": "/api/photos", "requestContext": {"http": {"method": "GET"}}}
    raw_directory = LOCAL / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    runs = []
    for scenario, source, status in (("normal", "local-api", 200), ("read-failure", "local-controlled", 503)):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        api.LOGGER.addHandler(handler)
        def read_page(**kwargs):
            if scenario == "read-failure":
                raise RuntimeError("controlled local failure; never contact AWS")
            return {"items": catalog, "lastKey": None}
        try:
            response = api.handle_request(event, read_page)
        finally:
            api.LOGGER.removeHandler(handler)
        if response["statusCode"] != status:
            raise ValueError("API demo returned unexpected HTTP status")
        # 每轮保留独立原始事件；make_run还会给交接文件分配唯一ID。
        from uuid import uuid4
        raw = raw_directory / f"{scenario}-{uuid4().hex[:12]}.jsonl"
        raw.write_text(stream.getvalue(), encoding="utf-8")
        prepared, skipped = convert(raw, "app-jsonl")
        run = make_run(prepared, source=source, scenario=scenario, raw_path=raw, skipped=skipped)
        write_json(run / "api-observation.json", {"execution": "local", "http_status": status,
                   "scenario": scenario, "request": "GET /api/photos", "AWS_called": False})
        runs.append(run)
    # 专门的缺字段样本，不经过正常事件转换器，不伪称API产生的日志。
    runs.append(make_run(b'{"level":"INFO","service":"format-test","message":"missing timestamp on purpose"}\n',
                         source="format-test", scenario="invalid-format"))
    public = []
    for run in runs:
        subprocess.run([sys.executable, str(checker), str(run / "events.jsonl")], check=True, capture_output=True)
        report = checker.parent / "reports/events.json"
        (run / "report-local.json").write_bytes(report.read_bytes())
        item, _ = sanitize(run / "manifest.json", run / "report-local.json", "local")
        public.append(item)
    write_json(LOCAL / "latest-demo.json", {"runs": [str(run) for run in runs], "checker_blob": CHECK_BLOB})
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checker", required=True, type=Path)
    args = parser.parse_args()
    try:
        for run in generate(args.checker):
            print(run)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Cannot create demo: {error}\n")


if __name__ == "__main__":
    main()
