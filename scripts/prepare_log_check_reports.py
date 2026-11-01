"""复核原始报告和本轮输入，只输出网页白名单字段；不上传AWS。"""
import argparse
from pathlib import Path
import re
from log_check_common import (SCENARIOS, SOURCES, inspect_input, now, private_path, read_json,
                              reason_category, sha, timestamp, write_json)


def sanitize(manifest_path, report_path, engine, cloud_uri=None, sns="unconfirmed", account_id_redacted=False):
    manifest_path, report_path = private_path(manifest_path), private_path(report_path)
    manifest, report = read_json(manifest_path), read_json(report_path)
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        raise ValueError("manifest and report must be objects")
    run = manifest.get("run_id", "")
    if not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{12}", run):
        raise ValueError("invalid run ID")
    if manifest.get("schema_version") != "1.0" or manifest.get("input_file") != "events.jsonl":
        raise ValueError("invalid manifest")
    source, scenario = manifest.get("source"), manifest.get("scenario")
    if (source not in SOURCES or scenario not in SCENARIOS
            or (scenario == "normal" and source not in {"local-api", "cloud-api"})
            or (scenario == "read-failure" and source != "local-controlled")
            or (scenario == "invalid-format" and source != "format-test")):
        raise ValueError("invalid source/scenario")
    input_path = private_path(manifest_path.parent / "events.jsonl")
    data = input_path.read_bytes()
    if sha(data) != manifest.get("input_sha256"):
        raise ValueError("input SHA256 mismatch")
    expected, counts, reason = inspect_input(data)
    if expected != manifest.get("expected_status") or counts != manifest.get("counts") or reason != manifest.get("reason_category"):
        raise ValueError("manifest does not match input")
    if expected != {"normal": "OK", "read-failure": "ALERT", "invalid-format": "INVALID"}[scenario]:
        raise ValueError("scenario does not match input")
    if engine == "local":
        if cloud_uri or sns not in {"unconfirmed", "not-applicable"}:
            raise ValueError("local engine cannot assert cloud execution or SNS delivery")
        if not isinstance(report.get("input_path"), str) or Path(report["input_path"]).resolve() != input_path:
            raise ValueError("report refers to another local input")
    elif engine == "aws":
        if account_id_redacted:
            # 本人已核对旧dev，聊天提供的报告仅遮盖桶名中的账号ID。
            # 保留原件，不猜回账号；仍严格匹配已知桶模板、本轮路径和报告内容。
            valid_uri = cloud_uri == f"s3://clc-dev-input-<账户ID>-ap-northeast-1/incoming/{run}/events.jsonl"
        else:
            valid_uri = isinstance(cloud_uri, str) and re.fullmatch(r"s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/incoming/" + re.escape(run) + r"/events\.jsonl", cloud_uri)
        if not valid_uri:
            raise ValueError("exact cloud input URI required for this run")
        if report.get("input_path") != cloud_uri:
            raise ValueError("report refers to another cloud input")
        if sns not in {"unconfirmed", "received"} or (sns == "received" and expected == "OK"):
            raise ValueError("invalid SNS evidence")
    else:
        raise ValueError("unknown execution engine")
    if report.get("schema_version") != "1.0" or report.get("status") != expected:
        raise ValueError("unexpected report schema/status")
    checked = timestamp(report.get("checked_at"))
    if not isinstance(report.get("execution_id"), str) or not report["execution_id"].strip():
        raise ValueError("missing execution ID")
    if expected == "INVALID":
        if report.get("counts", "missing") is not None or report.get("total_records", "missing") is not None:
            raise ValueError("INVALID counts must be null")
        if reason_category(report.get("reason")) != reason:
            raise ValueError("INVALID reason does not match input")
    else:
        actual = report.get("counts")
        if (not isinstance(actual, dict) or set(actual) != {"INFO", "WARN", "ERROR"}
                or any(type(v) is not int or v < 0 for v in actual.values()) or actual != counts
                or type(report.get("total_records")) is not int or report["total_records"] != sum(counts.values())
                or report.get("reason", "missing") is not None):
            raise ValueError("report counts/reason do not match input")
    public = {"id": run, "source": source, "scenario": scenario, "engine": engine,
              "checked_at": checked, "status": expected, "counts": counts,
              "total_records": sum(counts.values()) if counts is not None else None,
              "reason_category": reason, "notification": "not-applicable" if engine == "local" or expected == "OK" else sns}
    return public, {"run_id": run, "manifest": str(manifest_path), "report": str(report_path),
                    "input_sha256": sha(data), "report_sha256": sha(report_path.read_bytes()),
                    "engine": engine, "cloud_input_uri": cloud_uri, "sns_evidence": sns,
                    "account_id_redacted": bool(account_id_redacted and engine == "aws")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, action="append", type=Path)
    parser.add_argument("--report", required=True, action="append", type=Path)
    parser.add_argument("--engine", required=True, action="append", choices=("local", "aws"))
    parser.add_argument("--cloud-input-uri", action="append")
    parser.add_argument("--sns", action="append", choices=("unconfirmed", "received", "not-applicable"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--account-id-redacted", action="store_true",
                        help="accept owner-supplied clc-dev report with literal <账户ID>; full account identity cannot be checked")
    args = parser.parse_args()
    try:
        uris = args.cloud_input_uri or [None] * len(args.manifest)
        uris = [None if uri == "-" else uri for uri in uris]
        engines = args.engine * len(args.manifest) if len(args.engine) == 1 else args.engine
        notifications = args.sns or ["unconfirmed"]
        notifications = notifications * len(args.manifest) if len(notifications) == 1 else notifications
        if not len(args.manifest) == len(args.report) == len(uris) == len(engines) == len(notifications):
            raise ValueError("provide one report and optional cloud URI per manifest, in the same order")
        records, links = [], []
        for m, r, engine, uri, sns in zip(args.manifest, args.report, engines, uris, notifications):
            public, link = sanitize(m, r, engine, uri, sns, args.account_id_redacted)
            records.append(public)
            links.append(link)
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("duplicate runs")
        if len(records) > 30:
            raise ValueError("publish at most 30 reports")
        output = args.output.resolve()
        root = Path(__file__).resolve().parents[1]
        if not (output.is_relative_to((root / ".local/log-check").resolve())
                or output == root / "dist/log-check/reports.json"):
            raise ValueError("output must be local Log Check material or dist/log-check/reports.json")
        # 所有输入通过后再发布；验证失败不覆盖现有展示文件。
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1.0", "generated_at": now(), "reports": records}
        import json
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as temp:
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
            temporary = Path(temp.name)
        temporary.replace(output)
        from log_check_common import LOCAL
        LOCAL.mkdir(parents=True, exist_ok=True)
        write_json(LOCAL / ("publication-" + os.urandom(8).hex() + ".json"),
                   {"generated_at": payload["generated_at"], "display_sha256": sha(output.read_bytes()), "reports": links})
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Cannot publish reports: {error}\n")
    print(f"Prepared {len(records)} sanitized reports: {output}")


if __name__ == "__main__":
    main()
