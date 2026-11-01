"""只测本轮事件、交接和脱敏边界；不访问AWS或下载原图。"""
from copy import deepcopy
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from log_check_common import LOCAL, ROOT, MAX_BYTES, make_run, read_json, write_json
from prepare_log_check_input import convert, parse_message
from prepare_log_check_reports import sanitize

sys.path.insert(0, str(ROOT / "backend/photo-api"))
import lambda_function as api

EVENT = {"rawPath": "/api/photos", "requestContext": {"http": {"method": "GET"}},
         "headers": {"cookie": "PRIVATE_INVITATION"}, "rawQueryString": ""}
GOOD = {"timestamp": "2026-10-26T00:00:00+00:00", "level": "INFO", "service": "cj-photo-api",
        "message": "Photo catalog page read successfully", "code": "PHOTO_LIST_READ_OK"}


class LogCheckTests(unittest.TestCase):
    def setUp(self):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_api_normal_failure_no_leak_and_input_errors(self):
        stream = io.StringIO(); handler = logging.StreamHandler(stream); api.LOGGER.addHandler(handler)
        self.addCleanup(api.LOGGER.removeHandler, handler)
        self.assertEqual(api.handle_request(EVENT, lambda **kw: {"items": [], "lastKey": None})["statusCode"], 200)
        response = api.handle_request(EVENT, Mock(side_effect=RuntimeError("PRIVATE_EXCEPTION")))
        self.assertEqual(response["statusCode"], 503)
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([row["level"] for row in rows], ["INFO", "ERROR"])
        self.assertEqual([row["code"] for row in rows], ["PHOTO_LIST_READ_OK", "PHOTO_READ_FAILED"])
        for row in rows:
            parse_message(row)
        self.assertNotIn("PRIVATE", stream.getvalue() + response["body"])
        stream.truncate(0); stream.seek(0)
        reader = Mock()
        self.assertEqual(api.handle_request({**EVENT, "rawQueryString": "limit=999"}, reader)["statusCode"], 400)
        self.assertEqual(api.handle_request({**EVENT, "requestContext": {"http": {"method": "POST"}}}, reader)["statusCode"], 405)
        self.assertEqual(stream.getvalue(), ""); reader.assert_not_called()

    def test_api_bad_catalog_and_configuration_are_errors(self):
        for read, album in ((lambda **kw: {"items": [{}]}, "main"), (Mock(), "!")):
            with self.assertLogs(api.LOGGER, level="ERROR") as output:
                self.assertEqual(api.handle_request(EVENT, read, album)["statusCode"], 503)
            self.assertEqual(json.loads(output.records[0].getMessage())["code"], "PHOTO_READ_FAILED")

    def test_supported_cloudwatch_and_lambda_formats(self):
        encoded = json.dumps(GOOD)
        for message in (encoded, "[INFO]\t2026-10-26T00:00:00Z\trequest-id\t" + encoded,
                        {"message": encoded, "level": "INFO", "requestId": "PRIVATE"}, {"message": GOOD}):
            result = parse_message(message)
            self.assertEqual(set(result), {"timestamp", "level", "service", "message"})
        raw = self.directory / "cloudwatch.json"
        write_json(raw, {"events": [{"message": "START RequestId: private Version: $LATEST"},
                                   {"message": encoded}, {"message": "REPORT RequestId: private Duration: 1 ms"}]})
        data, skipped = convert(raw, "cloudwatch-json")
        self.assertEqual(skipped, 2); self.assertEqual(len(data.splitlines()), 1)
        self.assertNotIn(b"PRIVATE", data)

    def test_malformed_application_logs_never_silently_skipped(self):
        for row in ('{"service":"cj-photo-api",broken', 'some unexpected application error',
                    {**GOOD, "timestamp": "2026-10-26T00:00:00"}, {**GOOD, "message": "PRIVATE"},
                    {**GOOD, "code": "UNKNOWN"}, {"message": "invalid JSON"}):
            with self.assertRaises(ValueError): parse_message(row)
        raw = self.directory / "bad.jsonl"
        raw.write_text(json.dumps(GOOD) + '\n{"service":"cj-photo-api",broken', encoding="utf-8")
        with self.assertRaises(ValueError): convert(raw, "app-jsonl")
        for token in ("nextToken", "NextToken", "nextForwardToken"):
            write_json(raw, {"events": [], token: "more"})
            with self.assertRaises(ValueError): convert(raw, "cloudwatch-json")

    def test_input_limits_empty_and_private_directory(self):
        raw = self.directory / "large.jsonl"
        raw.write_text((json.dumps(GOOD) + "\n") * 1001, encoding="utf-8")
        with self.assertRaises(ValueError): convert(raw, "app-jsonl")
        raw.write_text((json.dumps({**GOOD, "extra": "x" * 5000}) + "\n") * 1000, encoding="utf-8")
        # 多余字段不传递，所以大小按白名单输出计算。
        self.assertLess(len(convert(raw, "app-jsonl")[0]), MAX_BYTES)
        from log_check_common import inspect_input
        self.assertEqual(inspect_input(b"x" * (MAX_BYTES + 1)), ("INVALID", None, "size"))
        raw.write_text("START RequestId: private\n", encoding="utf-8")
        with self.assertRaises(ValueError): convert(raw, "app-jsonl")
        with self.assertRaises(ValueError): convert(ROOT / "README.md", "app-jsonl")

    def demo_pairs(self):
        return [(Path(run) / "manifest.json", Path(run) / "report-local.json") for run in read_json(LOCAL / "latest-demo.json")["runs"]]

    def test_real_original_checker_reports_and_redaction(self):
        public = [sanitize(m, r, "local")[0] for m, r in self.demo_pairs()]
        self.assertEqual([p["status"] for p in public], ["OK", "ALERT", "INVALID"])
        self.assertIsNone(public[-1]["counts"]); self.assertIsNone(public[-1]["total_records"])
        self.assertTrue(all(p["engine"] == "local" for p in public))
        self.assertNotRegex(json.dumps(public), r"input_path|execution_id|requestId|s3://|C:\\\\")
        m, r = self.demo_pairs()[0]
        original = read_json(r); original.update(private_extra="PRIVATE", reason=None)
        path = self.directory / "extra.json"; write_json(path, original)
        self.assertNotIn("PRIVATE", json.dumps(sanitize(m, path, "local")[0]))

    def test_report_rejects_mismatch_tampering_and_invalid_nulls(self):
        m, r = self.demo_pairs()[0]; report = read_json(r)
        changes = ({"schema_version": "2"}, {"status": "ALERT"}, {"total_records": True},
                   {"counts": {"INFO": True, "WARN": 0, "ERROR": 0}},
                   {"counts": {"INFO": 2, "WARN": 0, "ERROR": 0}}, {"reason": "PRIVATE"},
                   {"input_path": "another-file.jsonl"}, {"checked_at": "2026-10-26T00:00:00"})
        path = self.directory / "bad-report.json"
        for change in changes:
            write_json(path, {**report, **change})
            with self.assertRaises(ValueError): sanitize(m, path, "local")
        m, r = self.demo_pairs()[-1]
        write_json(path, {**read_json(r), "total_records": 0})
        with self.assertRaises(ValueError): sanitize(m, path, "local")
        write_json(path, {**read_json(r), "reason": "PRIVATE arbitrary error"})
        with self.assertRaises(ValueError): sanitize(m, path, "local")
        # 清单和输入被单独编辑时，不能沿用原报告发布。
        m, r = self.demo_pairs()[0]
        manifest = read_json(m)
        local_manifest = self.directory / "manifest.json"
        write_json(local_manifest, manifest)
        (self.directory / "events.jsonl").write_bytes((m.parent / "events.jsonl").read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            sanitize(local_manifest, r, "local")

    def test_cloud_mapping_keeps_input_source_and_notification_separate(self):
        m, r = self.demo_pairs()[1]; report = read_json(r)
        uri = "s3://example-dev-input/" + read_json(m)["cloud_input_key"]
        path = self.directory / "cloud-report.json"; write_json(path, {**report, "input_path": uri})
        public, _ = sanitize(m, path, "aws", uri)
        self.assertEqual(public["source"], "local-controlled"); self.assertEqual(public["engine"], "aws")
        self.assertEqual(public["notification"], "unconfirmed")
        with self.assertRaises(ValueError): sanitize(m, path, "aws", uri + "wrong")
        with self.assertRaises(ValueError): sanitize(m, r, "local", sns="received")

    def test_cli_reject_does_not_overwrite_published_file(self):
        output = self.directory / "display.json"; output.write_text("KEEP", encoding="utf-8")
        m, r = self.demo_pairs()[0]
        bad = self.directory / "bad.json"; write_json(bad, {**read_json(r), "status": "ALERT"})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare_log_check_reports.py"),
                                "--manifest", str(m), "--report", str(bad), "--engine", "local", "--output", str(output)], capture_output=True)
        self.assertNotEqual(result.returncode, 0); self.assertEqual(output.read_text(), "KEEP")

    def test_redacted_report_requires_explicit_flag_and_known_dev_path(self):
        m, r = self.demo_pairs()[0]
        run = read_json(m)["run_id"]
        uri = f"s3://clc-dev-input-<账户ID>-ap-northeast-1/incoming/{run}/events.jsonl"
        path = self.directory / "owner-redacted.json"
        write_json(path, {**read_json(r), "input_path": uri})
        with self.assertRaises(ValueError): sanitize(m, path, "aws", uri)
        public, link = sanitize(m, path, "aws", uri, account_id_redacted=True)
        self.assertEqual(public["engine"], "aws"); self.assertTrue(link["account_id_redacted"])
        for wrong in (uri.replace("clc-dev-input", "another-bucket"), uri.replace(run, "another-run")):
            write_json(path, {**read_json(r), "input_path": wrong})
            with self.assertRaises(ValueError): sanitize(m, path, "aws", wrong, account_id_redacted=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
