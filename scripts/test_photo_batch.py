"""批量准备针对性测试。合成 JPEG 为测试替身，不调用 AWS。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from urllib.request import urlopen

from PIL import Image

from prepare_photos import (LOCAL, ROOT, digest, load_baseline, make_selection,
                            prepare_batch, read_json, validate_selection, write_json)
from photo_dev_server import create_server


class PhotoBatchTests(unittest.TestCase):
    def setUp(self):
        self.test_parent = LOCAL / "photo-app/batch-tests"
        self.test_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.test_parent)
        self.directory = Path(self.temporary.name).resolve()
        # TemporaryDirectory 只清理此处明确生成的测试目录。
        self.assertTrue(self.directory.is_relative_to(self.test_parent.resolve()))
        self.source = self.directory / "输入"
        self.source.mkdir()
        self.baseline = self.directory / "baseline.json"
        write_json(self.baseline, [])
        self.output = self.directory / "batch"

    def tearDown(self):
        self.temporary.cleanup()

    def jpeg(self, name="照片.JPEG", color=(40, 110, 180), orientation=None):
        file = self.source / name
        exif = Image.Exif()
        if orientation:
            exif[274] = orientation
        Image.new("RGB", (12, 8), color).save(file, "JPEG", exif=exif)
        return file

    def selection(self):
        return make_selection(self.source, None, [], None)

    def test_26_photos_split_preview_download_api_and_next_batch(self):
        before = {}
        for number in range(26):
            path = self.jpeg(f"照片 {number:02}.JPG", (number * 8, 80, 140), orientation=6 if number == 0 else None)
            before[path.name] = digest(path)
        output = prepare_batch(self.source, baseline_path=self.baseline, output=self.output)
        catalog = read_json(output / "catalog.json")
        self.assertEqual(len(catalog), 26)
        self.assertTrue(all("title" not in item for item in catalog))
        batches = [read_json(p)["cj-photo-catalog"] for p in sorted(output.glob("batch-*.json"))]
        self.assertEqual(list(map(len, batches)), [25, 1])
        self.assertEqual({p.name: digest(p) for p in self.source.iterdir()}, before)
        for item in catalog:
            self.assertEqual(digest(output / "s3" / item["originalKey"]), item["sha256"])
            self.assertEqual(item["sizeBytes"], (output / "s3" / item["originalKey"]).stat().st_size)
        for entry in read_json(output / "manifest.json")["s3Files"]:
            self.assertEqual(digest(output / "s3" / entry["key"]), entry["sha256"])
        with Image.open(output / "s3" / catalog[0]["previewKey"]) as image:
            self.assertEqual(image.size, (8, 12))
            self.assertNotIn(274, image.getexif())
        source = read_json(output / "source.json")
        server = create_server(catalog, source["directory"], port=0, asset_root=source["assetRoot"])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/photos") as response:
                page = json.load(response)
            self.assertEqual(len(page["photos"]), 24)
            with urlopen(base + "/api/photos?cursor=" + page["nextCursor"]) as response:
                self.assertEqual(len(json.load(response)["photos"]), 2)
            photo = page["photos"][0]
            with urlopen(base + photo["previewUrl"]) as response:
                self.assertEqual(response.headers.get_content_type(), "image/webp")
                self.assertGreater(len(response.read()), 0)
            with urlopen(base + photo["downloadUrl"]) as response:
                self.assertEqual(response.read(), (self.source / catalog[0]["filename"]).read_bytes())
            with urlopen(base + "/photos/index.html?lang=zh") as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        # 换成小批次：无旧 batch-002 残留，保留已知 26 条，不生成删除请求。
        subset = self.directory / "subset"
        subset.mkdir()
        shutil.copyfile(self.source / catalog[0]["filename"], subset / "改名.JPG")
        smaller = prepare_batch(subset, baseline_path=output / "baseline-after.json", output=self.directory / "smaller")
        self.assertEqual(len(read_json(smaller / "catalog.json")), 1)
        self.assertEqual(len(read_json(smaller / "baseline-after.json")), 26)
        self.assertEqual(len(list(smaller.glob("batch-*.json"))), 1)
        self.assertEqual(read_json(smaller / "catalog.json")[0]["id"], catalog[0]["id"])
        self.assertFalse((smaller / "photo-api.zip").exists())

    def test_duplicate_content_is_rejected(self):
        path = self.jpeg()
        (self.source / "duplicate.jpg").write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_selection(self.source, self.selection(), [])

    def test_duplicate_paths_orders_ids_and_filenames_are_rejected(self):
        self.jpeg("one.jpg")
        self.jpeg("two.jpg", (200, 10, 90))
        for field in ("id", "order", "previewKey", "filename"):
            selection = self.selection()
            selection["photos"][1][field] = selection["photos"][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "重复"):
                validate_selection(self.source, selection, [])

    def test_path_traversal_corrupt_and_disguised_files_are_rejected(self):
        self.jpeg()
        selection = self.selection()
        selection["photos"][0]["filename"] = "../outside.jpg"
        with self.assertRaises(ValueError):
            validate_selection(self.source, selection, [])
        (self.source / "照片.JPEG").write_bytes(b"not-a-jpeg")
        with self.assertRaises(OSError):
            validate_selection(self.source, self.selection(), [])
        Image.new("RGB", (2, 2)).save(self.source / "照片.JPEG", "PNG")
        with self.assertRaisesRegex(ValueError, "不是 JPEG"):
            validate_selection(self.source, self.selection(), [])

    def test_existing_identity_order_and_original_changes_are_rejected(self):
        self.jpeg()
        selection = self.selection()
        photo = selection["photos"][0]
        baseline = [{"id": photo["id"], "SK": f"PHOTO#000000001#{photo['id']}",
                     "previewKey": photo["previewKey"], "sha256": digest(self.source / photo["filename"])}]
        self.assertEqual(len(validate_selection(self.source, selection, baseline)), 1)
        for field, value in (("order", 9), ("previewKey", "assets/photos/changed.webp"), ("id", "another")):
            changed = deepcopy(selection)
            changed["photos"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_selection(self.source, changed, baseline)
        self.jpeg(color=(250, 5, 5))
        with self.assertRaisesRegex(ValueError, "原图"):
            validate_selection(self.source, selection, baseline)

    def test_empty_input_existing_output_and_outside_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "没有选择"):
            prepare_batch(self.source, baseline_path=self.baseline, output=self.output)
        self.jpeg()
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "已存在"):
            prepare_batch(self.source, baseline_path=self.baseline, output=self.output)
        self.assertEqual(marker.read_text(), "keep")
        with self.assertRaisesRegex(ValueError, ".local"):
            prepare_batch(self.source, baseline_path=self.baseline, output=ROOT / "dist/test-batch")

    def test_invalid_baseline_and_selection_are_rejected(self):
        write_json(self.baseline, {"wrong": []})
        with self.assertRaisesRegex(ValueError, "基准"):
            load_baseline(self.baseline)
        manifest = self.directory / "selection.json"
        for value in ([], {"albumId": "other"}, {"albumId": "main", "tableName": "cj-photo-catalog", "photos": []}):
            write_json(manifest, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_selection(self.source, manifest, [], None)

    def test_optional_title_and_low_level_stale_batch_rejection(self):
        self.jpeg()
        selection = self.selection()
        selection["photos"][0]["title"] = {"zh": "只填中文"}
        manifest = self.directory / "selection.json"
        write_json(manifest, selection)
        output = prepare_batch(self.source, selection_path=manifest, baseline_path=self.baseline, output=self.output)
        self.assertEqual(read_json(output / "catalog.json")[0]["title"], {"zh": "只填中文"})
        stale = self.directory / "stale"
        stale.mkdir()
        (stale / "batch-002.json").write_text("keep")
        result = subprocess.run([shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"),
            str(ROOT / "scripts/prepare-photo-data.cjs"), str(self.source), "--selection", str(manifest),
            "--output", str(stale), "--preview-root", str(output / "s3")], capture_output=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("拒绝覆盖", result.stderr)
        self.assertEqual((stale / "batch-002.json").read_text(), "keep")
        self.assertFalse((stale / "catalog.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
