"""固定维护入口的针对性测试；合成JPEG，不联网、不打开应用。"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import photo_maintenance as maintenance
import prepare_photos as core


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        parent = core.LOCAL / "photo-app/maintenance-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(parent.resolve()))
        self.source = self.directory / "选图"
        self.source.mkdir()
        self.original = self.source / "a-known.JPG"
        Image.new("RGB", (12, 8), (20, 120, 70)).save(self.original, "JPEG")
        self.known = {"PK": "ALBUM#main", "SK": "PHOTO#000000001#known", "id": "known",
                      "filename": self.original.name, "previewKey": "assets/photos/known.webp",
                      "originalKey": "photo-originals/main/known.jpg", "sizeBytes": self.original.stat().st_size,
                      "sha256": core.digest(self.original)}
        self.baseline = self.directory / "published.json"
        core.write_json(self.baseline, [self.known])
        self.latest = self.directory / "latest.json"
        self.output = self.directory / "batch"

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_published_skips_without_creating_batch_or_changing_state(self):
        before = self.baseline.read_bytes()
        result = maintenance.prepare_new(self.source, self.baseline, output=self.output, latest_path=self.latest)
        self.assertEqual(result, {"prepared": 0, "skipped": 1, "directory": None})
        self.assertFalse(self.output.exists())
        self.assertFalse(self.latest.exists())
        self.assertEqual(self.baseline.read_bytes(), before)

    def test_mixed_folder_prepares_only_new_and_keeps_published_state(self):
        new = self.source / "b-new.JPG"
        Image.new("RGB", (10, 16), (200, 40, 130)).save(new, "JPEG")
        before = self.baseline.read_bytes()
        result = maintenance.prepare_new(self.source, self.baseline, output=self.output, latest_path=self.latest)
        self.assertEqual(result["prepared"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.baseline.read_bytes(), before)
        catalog = core.read_json(self.output / "catalog.json")
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["filename"], new.name)
        self.assertTrue(catalog[0]["SK"].startswith("PHOTO#000000002#"))
        self.assertEqual(maintenance.latest_directory(self.latest, self.directory / "absent"), self.output)
        self.assertEqual(core.read_json(self.latest)["status"], "prepared-local-only")

    def test_duplicate_published_file_is_rejected_before_skip(self):
        shutil.copyfile(self.original, self.source / "duplicate.JPG")
        with self.assertRaisesRegex(ValueError, "重复"):
            maintenance.prepare_new(self.source, self.baseline, output=self.output, latest_path=self.latest)
        self.assertFalse(self.output.exists())

    def test_only_new_photos_are_prompted_for_location_and_choice_reaches_catalog(self):
        Image.new("RGB", (10, 16), (200, 40, 130)).save(self.source / "new.JPG", "JPEG")
        self.known["location"] = "富士山"
        core.write_json(self.baseline, [self.known])
        chooser = unittest.mock.Mock(return_value="  札幌  ")
        with redirect_stdout(io.StringIO()):
            maintenance.prepare_new(self.source, self.baseline, output=self.output, latest_path=self.latest, choose_location=chooser)
        chooser.assert_called_once_with("new.JPG", ["富士山", "札幌"], "")
        self.assertEqual(core.read_json(self.output / "catalog.json")[0]["location"], "札幌")
        self.assertEqual(core.read_json(self.baseline)[0]["location"], "富士山")

    def test_location_prompt_accepts_existing_name_previous_and_uncategorized(self):
        for value, expected in (("1", "札幌"), ("=", "富士山"), ("", ""), ("未分类", "")):
            with patch("builtins.input", return_value=value), redirect_stdout(io.StringIO()):
                self.assertEqual(maintenance.ask_location("sample.JPG", ["札幌"], "富士山"), expected)

    def test_new_photo_requires_a_place_and_can_reuse_previous_choice(self):
        with patch("builtins.input", side_effect=["", "未分类", "=", "1"]), redirect_stdout(io.StringIO()):
            self.assertEqual(maintenance.ask_new_location("sample.JPG", ["伊豆"]), "伊豆")
        with patch("builtins.input", return_value="="), redirect_stdout(io.StringIO()):
            self.assertEqual(maintenance.ask_new_location("sample.JPG", ["伊豆"], "箱根"), "箱根")

    def test_prepared_location_file_still_requires_explicit_user_confirmation(self):
        self.known["location"] = "富士山"; core.write_json(self.baseline, [self.known])
        assignments = self.directory / "locations.json"; core.write_json(assignments, {"known": "札幌"})
        def edit(data, confirm):
            self.assertEqual(data, {"known": "札幌"})
            approved = confirm({"target": {"account": "000000000000", "region": "ap-northeast-1"},
                "photos": [{**self.known, "location": "札幌"}]})
            self.assertFalse(approved)
            return {"status": "cancelled"}
        with patch.object(core, "DEFAULT_BASELINE", self.baseline), \
             patch("photo_location_maintenance.edit_locations", side_effect=edit), \
             patch("builtins.input", return_value=""), redirect_stdout(io.StringIO()):
            maintenance.maintain_locations(assignments)

    def test_recent_directory_cannot_point_outside_local(self):
        core.write_json(self.latest, {"directory": str(core.ROOT / "scripts")})
        with self.assertRaisesRegex(ValueError, "位置无效"):
            maintenance.latest_directory(self.latest, self.directory / "absent")

    def test_menu_can_exit_without_opening_or_preparing_anything(self):
        with patch.object(maintenance, "status", return_value={"knownPublishedCount": 8, "inputJpegCount": 3}), \
             patch("builtins.input", return_value="0"), \
             patch.object(maintenance, "open_directory") as opening, \
             patch.object(maintenance, "prepare_new") as preparing, redirect_stdout(io.StringIO()) as captured:
            maintenance.menu()
        opening.assert_not_called()
        preparing.assert_not_called()
        self.assertIn("8 张", captured.getvalue())

    def test_login_failure_does_not_continue_to_identity_or_other_operations(self):
        with patch.object(maintenance.shutil, "which", return_value="aws.exe"), \
             patch.object(maintenance.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "aws login")) as run, \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                maintenance.login_and_check_identity()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], "login")

    def test_login_uses_isolated_profile_and_only_reads_identity_after_success(self):
        with patch.object(maintenance.shutil, "which", return_value="aws.exe"), \
             patch.object(maintenance.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
             redirect_stdout(io.StringIO()):
            maintenance.login_and_check_identity()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual([command[1:3] for command in commands], [["login", "--profile"], ["sts", "get-caller-identity"]])
        for command in commands:
            self.assertEqual(command[command.index("--profile") + 1], "photo-maintenance")
            self.assertEqual(command[command.index("--region") + 1], "ap-northeast-1")

    def test_missing_aws_cli_does_not_try_to_launch_or_install_anything(self):
        with patch.object(maintenance.shutil, "which", return_value=None), \
             patch.object(maintenance.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "未找到"):
                maintenance.login_and_check_identity()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
