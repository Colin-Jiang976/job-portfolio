"""地点筛选/分页/维护事务的针对性检查；合成目录与AWS替身，不联网。"""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import prepare_photos as core
import lambda_function as api
from photo_locations import (CONFIG_KEY, clean_location, location_id, location_record,
                             registry, registry_json)
import photo_location_maintenance as maintenance
import photo_publish as publish
from test_photo_publish import FakeAws


def photo(number, label=None):
    pid = f"sample-{number}"
    return {"PK": "ALBUM#main", "SK": f"PHOTO#{number:09d}#{pid}", "id": pid,
            "previewKey": f"assets/photos/{pid}.webp", "originalKey": f"photo-originals/main/{pid}.jpg",
            "filename": f"照片{number}.JPG", "sizeBytes": 12, "sha256": f"{number:064x}",
            **({"location": label} if label is not None else {})}


def event(query=""):
    return {"rawPath": "/api/photos", "rawQueryString": query, "requestContext": {"http": {"method": "GET"}}}


class LocationApiTests(unittest.TestCase):
    def test_location_query_paginates_all_matches_not_just_first_all_photos_page(self):
        items = [photo(n, "札幌" if n % 2 else "富士山") for n in range(1, 107)] + [photo(107)]
        rows = sorted(items + [location_record(item) for item in items], key=lambda p: p["SK"])
        calls = []
        def read_page(*, partition, after, limit, prefix="PHOTO#"):
            calls.append(prefix)
            matching = [p for p in rows if p["SK"].startswith(prefix) and (not after or p["SK"] > after["SK"])]
            last = matching[limit-1] if len(matching) > limit else None
            return {"items": matching[:limit], "lastKey": {"PK": partition, "SK": last["SK"]} if last else None}
        cursor, sizes, ids = None, [], []
        selected = location_id("札幌")
        while True:
            query = "location=" + selected + ("&cursor=" + cursor if cursor else "")
            result = api.handle_request(event(query), read_page, read_locations=lambda _: registry(["札幌", "富士山"]))
            self.assertEqual(result["statusCode"], 200)
            data = json.loads(result["body"])
            self.assertEqual(data["selectedLocation"], selected)
            self.assertTrue(all(p["location"] == "札幌" for p in data["photos"]))
            sizes.append(len(data["photos"])); ids.extend(p["id"] for p in data["photos"])
            cursor = data["nextCursor"]
            if not cursor: break
        self.assertEqual(sizes, [24, 24, 5]); self.assertEqual(len(set(ids)), 53)
        self.assertTrue(all(p == f"LOCATION#{selected}#PHOTO#" for p in calls))
        result = api.handle_request(event("location=unassigned"), read_page)
        self.assertEqual(len(json.loads(result["body"])["photos"]), 1)
        result = api.handle_request(event("location=" + location_id("没有照片的地点")), read_page)
        self.assertEqual(json.loads(result["body"]), {"photos": [], "nextCursor": None})

    def test_cross_location_and_all_page_cursors_rejected_before_queries(self):
        read = Mock()
        canonical = photo(1, "札幌")
        keys = [canonical, location_record(canonical), location_record(photo(2, "富士山"))]
        for key in keys:
            cursor = api.encode_cursor({k: key[k] for k in ("PK", "SK")})
            for selected in ("", location_id("札幌"), location_id("富士山")):
                correct = (not selected and key == canonical) or key["SK"].startswith(f"LOCATION#{selected}#")
                if correct: continue
                result = api.handle_request(event("cursor=" + cursor + ("&location="+selected if selected else "")), read)
                self.assertEqual(result["statusCode"], 400)
        read.assert_not_called()

    def test_bad_or_duplicate_location_parameters_do_not_query(self):
        read = Mock()
        for query in ("location=札幌", "location=../foo", "location=unassigned&location=unassigned", "cursor=&cursor=", "scan=1"):
            self.assertEqual(api.handle_request(event(query), read)["statusCode"], 400)
        read.assert_not_called()

    def test_lambda_uses_two_scoped_queries_and_no_scan_or_filter_expression(self):
        item = photo(1, "札幌")
        def query(**request):
            if request["Limit"] == 1:
                self.assertEqual(request["ExpressionAttributeValues"][":s"], {"S": CONFIG_KEY})
                return {"Items": [{"locationsJson": {"S": registry_json(["札幌"])}}]}
            self.assertEqual(request["ExpressionAttributeValues"][":photo"], {"S": f"LOCATION#{location_id('札幌')}#PHOTO#"})
            self.assertEqual(request["Limit"], 24)
            self.assertNotIn("FilterExpression", request); self.assertNotIn("IndexName", request)
            self.assertTrue(request["ConsistentRead"])
            return {"Items": [publish.marshal(item)]}
        client = Mock(); client.query.side_effect = query
        with patch.object(api, "_client", client), patch.dict(os.environ, {"PHOTO_TABLE": "cj-photo-catalog"}):
            result = api.lambda_handler(event("location=" + location_id("札幌")), None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(client.query.call_count, 2); client.scan.assert_not_called()

    def test_wrong_location_record_fails_closed(self):
        with self.assertLogs(api.LOGGER, level="ERROR"):
            result = api.handle_request(event("location="+location_id("札幌")),
                lambda **_: {"items": [photo(1, "富士山")]})
        self.assertEqual(result["statusCode"], 503)

    def test_location_text_is_bounded_and_normalized(self):
        self.assertEqual(clean_location("  札幌  "), "札幌")
        self.assertEqual(location_id(""), "unassigned")
        for label in ("x" * 61, "札\n幌", [], "\u202e札幌"):
            with self.assertRaises(ValueError): clean_location(label)


class LocationMaintenanceTests(unittest.TestCase):
    def setUp(self):
        parent = core.LOCAL / "photo-app/location-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temp.name)
        self.baseline = self.directory / "published.json"
        self.items = [photo(1), photo(2)]
        core.write_json(self.baseline, self.items)
        self.target = {"profile": "photo-maintenance", "region": "ap-northeast-1", "account": "000000000000",
            "principalArn": "arn:aws:iam::000000000000:user/clc-admin", "table": "cj-photo-catalog",
            "bucket": "cj-job-portfolio-20261024-resume"}
        self.target_path = self.directory / "target.json"; core.write_json(self.target_path, self.target)
        self.aws = FakeAws(self.target)
        self.aws.items = {p["SK"]: publish.marshal(p) for p in self.items}

    def tearDown(self):
        self.temp.cleanup()

    def run_edit(self, assignments=None, confirm=lambda review: True):
        with redirect_stdout(io.StringIO()):
            return maintenance.edit_locations(assignments or {p["id"]: "札幌" for p in self.items}, confirm,
                baseline_path=self.baseline, target_path=self.target_path, aws=self.aws)

    def test_cancel_has_no_writes_or_local_snapshot_changes(self):
        before = self.baseline.read_bytes()
        self.assertEqual(self.run_edit(confirm=lambda _: False)["status"], "cancelled")
        self.assertEqual(self.aws.write_attempts, 0); self.assertEqual(self.baseline.read_bytes(), before)

    def test_legacy_photos_migrate_atomically_without_s3_or_iam_calls(self):
        self.assertEqual(self.run_edit()["status"], "verified")
        self.assertEqual(len(self.aws.items), 5)
        for item in core.read_json(self.baseline):
            self.assertEqual(item["location"], "札幌")
            self.assertEqual(self.aws.items[location_record(item)["SK"]], publish.marshal(location_record(item)))
        self.assertTrue(all(service in {"dynamodb", "sts"} for service, _, _ in self.aws.calls))
        for before, after in zip(self.items, core.read_json(self.baseline)):
            self.assertEqual(before, {k:v for k,v in after.items() if k != "location"})

    def test_partial_completion_can_resume_without_overwriting_another_change(self):
        before = self.baseline.read_bytes(); self.aws.fail_write = 3
        with self.assertRaises(publish.PublishError): self.run_edit()
        self.assertEqual(self.baseline.read_bytes(), before)
        self.assertEqual(self.aws.items[self.items[0]["SK"]]["location"], {"S": "札幌"})
        self.assertNotIn("location", self.aws.items[self.items[1]["SK"]])
        self.aws.fail_write = None
        self.assertEqual(self.run_edit()["status"], "verified")
        self.assertEqual(len(self.aws.items), 5)

    def test_reassign_moves_query_record_and_keeps_original_paths(self):
        self.run_edit()
        first = core.read_json(self.baseline)[0]; old_key = location_record(first)["SK"]
        self.run_edit({first["id"]: "富士山"})
        updated = core.read_json(self.baseline)[0]
        self.assertNotIn(old_key, self.aws.items)
        self.assertIn(location_record(updated)["SK"], self.aws.items)
        self.assertEqual(updated["originalKey"], first["originalKey"])

    def test_racing_canonical_edit_rejects_entire_transaction(self):
        def race(_):
            self.aws.items[self.items[0]["SK"]]["filename"] = {"S": "other.JPG"}
            return True
        with self.assertRaises(publish.PublishError): self.run_edit(confirm=race)
        self.assertEqual(self.aws.items[self.items[0]["SK"]]["filename"], {"S": "other.JPG"})
        self.assertNotIn(location_record({**self.items[0], "location": "札幌"})["SK"], self.aws.items)
        self.assertEqual(core.read_json(self.baseline), self.items)

    def test_wrong_identity_is_rejected_before_writes(self):
        self.aws.account = "111111111111"
        with self.assertRaisesRegex(publish.PublishError, "身份"): self.run_edit()
        self.assertEqual(self.aws.write_attempts, 0)

    def test_registry_conflict_does_not_erase_an_existing_place(self):
        maintenance.ensure_registry(self.aws, self.target, ["札幌"])
        maintenance.ensure_registry(self.aws, self.target, ["富士山"])
        _, entries = maintenance.read_registry(self.aws, self.target)
        self.assertEqual({r["label"] for r in entries}, {"札幌", "富士山"})

    def test_failed_registration_never_leaves_half_a_photo_pair(self):
        item = {**photo(3), "location": "札幌"}
        self.aws.items[location_record(item)["SK"]] = {**publish.marshal(location_record(item)), "filename": {"S": "foreign.JPG"}}
        with self.assertRaises(publish.PublishError): maintenance.register_photo(self.aws, self.target, item)
        self.assertNotIn(item["SK"], self.aws.items)


if __name__ == "__main__":
    unittest.main(verbosity=2)
