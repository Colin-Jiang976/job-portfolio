"""新增批次看图分组到发布材料的针对性检查；图片合成，AWS替身。"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
import json

from PIL import Image
import prepare_photos as core
from photo_maintenance import prepare_new
from photo_new_batch import finish_locations
from photo_location_picker import new_batch_server
import photo_publish as publish
from test_photo_publish import FakeAws


class NewBatchTests(unittest.TestCase):
    def setUp(self):
        parent = core.LOCAL / "photo-app/new-group-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temp.name)
        source = self.directory / "input"; source.mkdir()
        for n, color in enumerate(((10, 100, 40), (190, 40, 80))):
            Image.new("RGB", (12, 8), color).save(source / f"sample-{n}.JPG", "JPEG")
        self.baseline = self.directory / "published.json"; core.write_json(self.baseline, [])
        self.batch = self.directory / "batch"
        with redirect_stdout(io.StringIO()):
            prepare_new(source, self.baseline, output=self.batch, latest_path=self.directory / "latest.json")
        self.photos = core.read_json(self.batch / "catalog.json")
        self.labels = {p["id"]: "伊豆" for p in self.photos}
        self.target = {"profile": "photo-maintenance", "region": "ap-northeast-1", "account": "000000000000",
            "principalArn": "arn:aws:iam::000000000000:user/clc-admin", "table": "cj-photo-catalog",
            "bucket": "cj-job-portfolio-20261024-resume"}
        self.target_path = self.directory / "target.json"; core.write_json(self.target_path, self.target)

    def tearDown(self):
        self.temp.cleanup()

    def finish(self, labels=None):
        with patch.object(core, "DEFAULT_BASELINE", self.baseline):
            return finish_locations(self.batch, labels or self.labels)

    def test_partial_grouping_keeps_original_material_unpublishable(self):
        before = (self.batch / "catalog.json").read_bytes()
        self.assertFalse(self.finish({**self.labels, self.photos[0]["id"]: ""})["complete"])
        self.assertEqual((self.batch / "catalog.json").read_bytes(), before)
        with self.assertRaisesRegex(publish.PublishError, "必须填写拍摄地点"):
            publish.make_plan(self.batch, baseline_path=self.baseline, target_path=self.target_path)

    def test_full_grouping_updates_all_metadata_without_rebuilding_images_and_can_publish(self):
        hashes = {p: core.digest(p) for p in (self.batch / "s3").rglob("*") if p.is_file()}
        self.assertTrue(self.finish()["complete"])
        self.assertEqual({p: core.digest(p) for p in hashes}, hashes)
        self.assertTrue(all(p["location"] == "伊豆" for p in core.read_json(self.batch / "catalog.json")))
        rows = core.read_json(self.batch / "batch-001.json")["cj-photo-catalog"]
        self.assertTrue(all(row["PutRequest"]["Item"]["location"] == {"S": "伊豆"} for row in rows))
        plan = publish.make_plan(self.batch, baseline_path=self.baseline, target_path=self.target_path)
        aws = FakeAws(self.target)
        with redirect_stdout(io.StringIO()):
            result = publish.publish(plan, lambda _: True, aws=aws, published_path=self.baseline,
                                     state_path=self.directory / "state.json")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(aws.objects), 4); self.assertEqual(len(aws.items), 5)

    def test_changed_baseline_and_incomplete_finalization_block_publication(self):
        core.write_json(self.baseline, [self.photos[0]])
        with self.assertRaisesRegex(ValueError, "基准发生变化"):
            self.finish()
        core.write_json(self.batch / "location-finalizing.json", {})
        with self.assertRaisesRegex(publish.PublishError, "地点资料尚未完成"):
            publish.make_plan(self.batch, baseline_path=self.baseline, target_path=self.target_path)

    def test_http_save_progress_then_finish_does_not_call_aws(self):
        with patch.object(core, "DEFAULT_BASELINE", self.baseline):
            server = new_batch_server(self.batch)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                def catalog():
                    with urlopen(server.picker_url + "api/catalog", timeout=5) as response:
                        return json.load(response)
                def save(labels):
                    data = json.dumps({"baselineHash": catalog()["baselineHash"], "assignments": labels}).encode()
                    request = Request(server.picker_url + "api/save", data=data,
                        headers={"Content-Type": "application/json", "X-Photo-Picker": "local-save"})
                    with urlopen(request, timeout=5) as response:
                        return json.load(response)
                self.assertTrue(catalog()["requireLocations"])
                with patch("subprocess.run") as process:
                    partial = save({**self.labels, self.photos[0]["id"]: ""})
                    self.assertEqual(partial["remaining"], 1)
                    complete = save(self.labels)
                    self.assertTrue(complete["complete"])
                    self.assertTrue(save(self.labels)["complete"])  # 保存后再次保存，书签已更新。
                    process.assert_not_called()
                self.assertEqual(core.read_json(self.baseline), [])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
