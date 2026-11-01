"""发布流程测试：AWS完全替身；只生成本地合成JPEG，不操作真实账号。"""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import re
import unittest

from PIL import Image

import prepare_photos as core
from photo_maintenance import prepare_new
import photo_publish as publish


class FakeAws:
    def __init__(self, target):
        self.target = target
        self.account = target["account"]
        self.objects = {}
        self.items = {}
        self.calls = []
        self.write_attempts = 0
        self.fail_write = None
        self.full_checksum = True

    def call(self, service, operation, request, extra=()):
        self.calls.append((service, operation, deepcopy(request)))
        if operation in ("put-object", "put-item", "transact-write-items"):
            self.write_attempts += 1
            if self.write_attempts == self.fail_write:
                raise publish.AwsError("InjectedFailure", operation)
        if operation == "get-caller-identity":
            return {"Account": self.account, "Arn": self.target["principalArn"]}
        if operation == "describe-table":
            return {"Table": {"TableStatus": "ACTIVE", "TableArn": f"arn:aws:dynamodb:ap-northeast-1:{self.account}:table/cj-photo-catalog"}}
        if operation == "head-bucket":
            if request["ExpectedBucketOwner"] != self.account:
                raise publish.AwsError("403", operation)
            return {}
        if operation == "query":
            keys = [key for key in self.items if key.startswith("PHOTO#")]
            return {"Items": [] if not keys else [{"SK": {"S": max(keys)}}]}
        if operation == "get-item":
            assert request["ConsistentRead"] is True
            item = self.items.get(request["Key"]["SK"]["S"])
            return {"Item": deepcopy(item)} if item else {}
        if operation == "head-object":
            if request["Key"] not in self.objects:
                raise publish.AwsError("404", operation)
            data = self.objects[request["Key"]]
            result = {"ContentLength": len(data)}
            if self.full_checksum:
                result["ChecksumSHA256"] = base64.b64encode(hashlib.sha256(data).digest()).decode()
            return result
        if operation == "get-object":
            Path(extra[0]).write_bytes(self.objects[request["Key"]])
            return {}
        if operation == "put-object":
            assert request["IfNoneMatch"] == "*"
            assert request["ExpectedBucketOwner"] == self.account
            if request["Key"] in self.objects:
                raise publish.AwsError("PreconditionFailed", operation)
            data = Path(extra[1]).read_bytes()
            if base64.b64encode(hashlib.sha256(data).digest()).decode() != request["ChecksumSHA256"]:
                raise publish.AwsError("BadDigest", operation)
            self.objects[request["Key"]] = data
            return {}
        if operation == "put-item":
            key = request["Item"]["SK"]["S"]
            if not self.condition(request, self.items.get(key, {})):
                raise publish.AwsError("ConditionalCheckFailedException", operation)
            self.items[key] = deepcopy(request["Item"])
            return {}
        if operation == "transact-write-items":
            actions = request["TransactItems"]
            for action in actions:
                kind, body = next(iter(action.items()))
                key = body.get("Item", body.get("Key"))["SK"]["S"]
                if not self.condition(body, self.items.get(key, {})):
                    raise publish.AwsError("TransactionCanceledException", operation)
            for action in actions:
                kind, body = next(iter(action.items()))
                key = body.get("Item", body.get("Key"))["SK"]["S"]
                if kind == "Put": self.items[key] = deepcopy(body["Item"])
                elif kind == "Delete": self.items.pop(key, None)
            return {}
        raise AssertionError("Unexpected action " + service + " " + operation)

    @staticmethod
    def condition(request, item):
        names = request.get("ExpressionAttributeNames", {})
        values = request.get("ExpressionAttributeValues", {})
        for clause in request["ConditionExpression"].split(" AND "):
            missing = re.fullmatch(r"attribute_not_exists\((#\w+)\)", clause)
            if missing:
                if names[missing[1]] in item: return False
                continue
            equal = re.fullmatch(r"(#\w+) = (:\w+)", clause)
            if not equal: raise AssertionError("Unsupported test condition: " + clause)
            if item.get(names[equal[1]]) != values[equal[2]]: return False
        return True


class PublishTests(unittest.TestCase):
    def setUp(self):
        parent = core.LOCAL / "photo-app/publish-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(parent.resolve()))
        source = self.directory / "选图"
        source.mkdir()
        for number, color in enumerate(((20, 140, 50), (180, 60, 210))):
            Image.new("RGB", (12, 8), color).save(source / f"照片{number}.JPG", "JPEG")
        self.baseline = self.directory / "published.json"
        core.write_json(self.baseline, [])
        self.state = self.directory / "state.json"
        self.batch = self.directory / "batch"
        with redirect_stdout(io.StringIO()):
            prepare_new(source, self.baseline, output=self.batch, latest_path=self.directory / "latest.json",
                        choose_location=lambda *_: "札幌")
        self.target = {"profile": "photo-maintenance", "region": "ap-northeast-1", "account": "000000000000",
                       "principalArn": "arn:aws:iam::000000000000:user/clc-admin", "table": "cj-photo-catalog",
                       "bucket": "cj-job-portfolio-20261024-resume"}
        self.target_path = self.directory / "target.json"
        core.write_json(self.target_path, self.target)
        self.aws = FakeAws(self.target)

    def tearDown(self):
        self.temporary.cleanup()

    def plan(self):
        return publish.make_plan(self.batch, baseline_path=self.baseline, target_path=self.target_path)

    def run_publish(self, *, confirm=lambda review: True):
        with redirect_stdout(io.StringIO()):
            return publish.publish(self.plan(), confirm, aws=self.aws, published_path=self.baseline, state_path=self.state)

    def test_full_batch_uploads_before_registering_and_advances_snapshot_after_verification(self):
        result = self.run_publish()
        self.assertEqual(result["status"], "verified")
        self.assertEqual((result["uploaded"], result["registered"]), (4, 2))
        self.assertEqual(len(core.read_json(self.baseline)), 2)
        actions = [op for _, op, _ in self.aws.calls if op in ("put-object", "put-item", "transact-write-items")]
        self.assertEqual(actions, ["put-object"] * 4 + ["put-item"] + ["transact-write-items"] * 2)
        self.assertEqual(len(self.aws.items), 5)  # 两张照片+两条地点目录+一条地点选项。
        self.assertEqual(core.read_json(self.state)["count"], 2)

    def test_cancel_is_read_only_and_does_not_change_snapshot(self):
        result = self.run_publish(confirm=lambda review: False)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.aws.write_attempts, 0)
        self.assertEqual(core.read_json(self.baseline), [])
        self.assertFalse(self.state.exists())

    def test_new_photos_without_a_place_are_rejected_before_aws_calls(self):
        path = self.batch / "catalog.json"
        original = core.read_json(path)
        for value in (None, "", "未分类"):
            changed = deepcopy(original)
            if value is None: changed[0].pop("location")
            else: changed[0]["location"] = value
            core.write_json(path, changed)
            with self.assertRaisesRegex(publish.PublishError, "必须填写拍摄地点"):
                self.plan()
        self.assertEqual(self.aws.calls, [])

    def test_wrong_identity_is_rejected_before_writes(self):
        self.aws.account = "111111111111"
        with self.assertRaisesRegex(publish.PublishError, "身份"):
            self.run_publish()
        self.assertEqual(self.aws.write_attempts, 0)
        self.assertEqual(core.read_json(self.baseline), [])

    def test_conflicting_cloud_object_is_not_overwritten(self):
        entry = self.plan()["files"][0]
        self.aws.objects[entry["key"]] = b"different"
        with self.assertRaisesRegex(publish.PublishError, "拒绝覆盖"):
            self.run_publish()
        self.assertEqual(self.aws.objects[entry["key"]], b"different")
        self.assertEqual(self.aws.write_attempts, 0)

    def test_conflicting_cloud_record_is_not_overwritten(self):
        item = self.plan()["items"][0]
        self.aws.items[item["SK"]] = {**publish.marshal(item), "filename": {"S": "edited.JPG"}}
        with self.assertRaisesRegex(publish.PublishError, "拒绝覆盖"):
            self.run_publish()
        self.assertEqual(self.aws.write_attempts, 0)

    def test_same_size_cloud_object_with_different_content_is_rejected(self):
        entry = self.plan()["files"][0]
        data = bytearray((self.batch / "s3" / entry["key"]).read_bytes())
        data[-1] ^= 1
        self.aws.objects[entry["key"]] = bytes(data)
        with self.assertRaisesRegex(publish.PublishError, "内容不同"):
            self.run_publish()
        self.assertEqual(self.aws.write_attempts, 0)

    def test_unknown_live_order_position_requires_sync_before_writes(self):
        self.aws.items["PHOTO#000000999#foreign"] = {"SK": {"S": "PHOTO#000000999#foreign"}}
        with self.assertRaisesRegex(publish.PublishError, "末尾位置"):
            self.run_publish()
        self.assertEqual(self.aws.write_attempts, 0)

    def test_local_file_changed_during_review_is_not_uploaded(self):
        entry = self.plan()["files"][0]
        def change_file(review):
            (self.batch / "s3" / entry["key"]).write_bytes(b"changed during review")
            return True
        with self.assertRaisesRegex(publish.PublishError, "本地图片变化"):
            self.run_publish(confirm=change_file)
        self.assertEqual(self.aws.write_attempts, 0)
        self.assertEqual(core.read_json(self.baseline), [])

    def test_partial_upload_has_no_directory_writes_and_can_resume(self):
        self.aws.fail_write = 2
        with self.assertRaises(publish.PublishError):
            self.run_publish()
        self.assertEqual(len(self.aws.objects), 1)
        self.assertEqual(len(self.aws.items), 0)
        self.assertEqual(core.read_json(self.baseline), [])
        self.aws.fail_write = None
        result = self.run_publish()
        self.assertEqual(result["status"], "verified")
        self.assertEqual((result["reusedFiles"], result["uploaded"]), (1, 3))

    def test_partial_registration_resumes_without_reuploading_or_replacing(self):
        self.aws.fail_write = 7  # 四文件+地点选项+第一张双目录事务完成，第二张失败。
        with self.assertRaises(publish.PublishError):
            self.run_publish()
        self.assertEqual((len(self.aws.objects), len(self.aws.items)), (4, 3))
        self.assertEqual(core.read_json(self.baseline), [])
        self.aws.fail_write = None
        result = self.run_publish()
        self.assertEqual(result["status"], "verified")
        self.assertEqual((result["uploaded"], result["registered"]), (0, 1))
        self.assertEqual((result["reusedFiles"], result["reusedRecords"]), (4, 1))

    def test_matching_object_without_sha_header_is_read_back(self):
        entry = self.plan()["files"][0]
        self.aws.objects[entry["key"]] = (self.batch / "s3" / entry["key"]).read_bytes()
        self.aws.full_checksum = False
        result = self.run_publish()
        self.assertEqual(result["status"], "verified")
        self.assertTrue(any(op == "get-object" for _, op, _ in self.aws.calls))

    def test_tampered_material_is_rejected_before_any_aws_request(self):
        entry = self.plan()["files"][0]
        (self.batch / "s3" / entry["key"]).write_bytes(b"changed")
        with self.assertRaisesRegex(publish.PublishError, "材料已变化"):
            self.run_publish()
        self.assertEqual(self.aws.calls, [])

    def test_already_published_batch_is_a_local_noop(self):
        self.run_publish()
        self.aws.calls.clear()
        result = self.run_publish()
        self.assertEqual(result["status"], "already-recorded")
        self.assertEqual(self.aws.calls, [])

    def test_old_batch_stays_a_noop_after_locations_are_edited(self):
        self.run_publish()
        core.write_json(self.baseline, [{**item, "location": "札幌"} for item in core.read_json(self.baseline)])
        self.aws.calls.clear()
        self.assertEqual(self.run_publish()["status"], "already-recorded")
        self.assertEqual(self.aws.calls, [])

    def test_changed_local_snapshot_during_review_prevents_writes(self):
        def change_during_review(review):
            self.baseline.write_text("[ ]\n", encoding="utf-8")
            return True
        with self.assertRaisesRegex(publish.PublishError, "确认期间"):
            self.run_publish(confirm=change_during_review)
        self.assertEqual(self.aws.write_attempts, 0)

    def test_racing_record_is_conditionally_rejected_and_not_overwritten(self):
        item = self.plan()["items"][0]
        def race(review):
            self.aws.items[item["SK"]] = {**publish.marshal(item), "filename": {"S": "changed.JPG"}}
            return True
        with self.assertRaises(publish.PublishError):
            self.run_publish(confirm=race)
        self.assertEqual(self.aws.items[item["SK"]]["filename"], {"S": "changed.JPG"})
        self.assertEqual(core.read_json(self.baseline), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
