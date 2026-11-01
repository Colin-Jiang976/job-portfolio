"""本地批量分组的保存/访问/冲突检查；不调用AWS、不改真实照片和快照。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import prepare_photos as core
import photo_location_picker as picker


class PickerTests(unittest.TestCase):
    def setUp(self):
        parent = core.LOCAL / "photo-app/location-drafts/picker-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temp.name).resolve()
        self.baseline = self.directory / "catalog.json"
        self.items = [{"PK": "ALBUM#main", "SK": f"PHOTO#{n:09d}#test-{n}", "id": f"test-{n}",
            "previewKey": f"assets/photos/test-{n}.webp", "originalKey": f"photo-originals/main/test-{n}.jpg",
            "filename": f"test-{n}.JPG", "sizeBytes": 12, "sha256": f"{n:064x}"} for n in (1, 2)]
        core.write_json(self.baseline, self.items)
        self.latest = self.directory / "latest.json"
        self.server = picker.create_server(baseline_path=self.baseline, latest_path=self.latest,
            previews={}, draft_root=self.directory / "drafts")
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True); self.worker.start()
        self.base = self.server.picker_url

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(timeout=2)
        self.temp.cleanup()

    def request(self, route="api/catalog", data=None, headers=None):
        options = {"headers": headers or {}}
        if data is not None:
            options["data"] = json.dumps(data, ensure_ascii=False).encode("utf-8")
            options["headers"] = {"Content-Type": "application/json", "X-Photo-Picker": "local-save", **options["headers"]}
        try:
            response = urlopen(Request(self.base + route, **options), timeout=4)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def payload(self):
        return {"baselineHash": core.digest(self.baseline), "assignments": {"test-1": "伊豆", "test-2": "内蒙古"}}

    def test_save_and_reload_preserves_grouping_and_does_not_change_published_catalog(self):
        before = self.baseline.read_bytes()
        with patch("subprocess.run") as process:
            code, body = self.request(data=self.payload(), route="api/save")
            self.assertEqual(code, 200); self.assertFalse(json.loads(body)["awsCalled"])
            process.assert_not_called()
        path = picker.saved_assignments(self.baseline, self.latest)
        self.assertEqual(core.read_json(path), self.payload()["assignments"])
        code, body = self.request()
        self.assertEqual({p["id"]: p["location"] for p in json.loads(body)["photos"]}, self.payload()["assignments"])
        self.assertEqual(self.baseline.read_bytes(), before)

    def test_partial_or_unknown_photo_list_is_not_saved(self):
        for assignments in ({"test-1": "箱根"}, {"test-1": "箱根", "test-2": "东京", "other": "伊豆"}):
            self.assertEqual(self.request("api/save", {**self.payload(), "assignments": assignments})[0], 400)
        self.assertFalse(self.latest.exists())

    def test_changed_published_baseline_rejects_save(self):
        payload = self.payload()
        core.write_json(self.baseline, [{**p, "location": "箱根"} for p in self.items])
        self.assertEqual(self.request("api/save", payload)[0], 409)
        self.assertFalse(self.latest.exists())

    def test_foreign_origin_and_missing_save_header_and_private_routes_rejected(self):
        self.assertEqual(self.request(headers={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request("api/save", self.payload(), {"X-Photo-Picker": ""})[0], 403)
        self.assertEqual(self.request("../published-catalog.json")[0], 404)
        self.assertEqual(self.request("preview/test-1")[0], 404)
        self.assertFalse(self.latest.exists())

    def test_saved_plan_allows_partial_publish_retry_but_rejects_other_changes(self):
        self.request("api/save", self.payload())
        core.write_json(self.baseline, [{**self.items[0], "location": "伊豆"}, self.items[1]])
        self.assertTrue(picker.saved_assignments(self.baseline, self.latest).is_file())
        core.write_json(self.baseline, [{**self.items[0], "location": "东京"}, self.items[1]])
        with self.assertRaisesRegex(ValueError, "另行修改"):
            picker.saved_assignments(self.baseline, self.latest)

    def test_reopening_server_uses_previously_saved_assignments(self):
        self.request("api/save", self.payload())
        reopened = picker.create_server(baseline_path=self.baseline, latest_path=self.latest,
            previews={}, draft_root=self.directory / "drafts")
        worker = threading.Thread(target=reopened.serve_forever, daemon=True); worker.start()
        try:
            with urlopen(reopened.picker_url + "api/catalog", timeout=4) as response:
                data = json.load(response)
            self.assertEqual({p["id"]: p["location"] for p in data["photos"]}, self.payload()["assignments"])
        finally:
            reopened.shutdown(); reopened.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
