"""静态更新/恢复工具的针对性检查；全程本地副本，不访问AWS、不改dist。"""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import site_release as release


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = release.LOCAL / 'tests'
        parent.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=parent)
        cls.directory = Path(cls.temporary.name).resolve()
        assert cls.directory.is_relative_to(parent.resolve())
        cls.base = release.make_release(output=cls.directory / 'reference')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def copy(self):
        target = self.directory / self._testMethodName
        return release.restore(self.base / 'snapshot.zip', target)

    def test_round_trip_restores_exact_files_and_versions(self):
        restored = self.copy()
        manifest = release.verify_archive(self.base / 'snapshot.zip')
        self.assertTrue(all(release.sha(restored / name) == item['sha256'] for name, item in manifest['files'].items()))
        self.assertTrue(release.check_site(restored)['ok'])

    def test_missing_reference_prevents_packaging(self):
        source = self.copy()
        file = source / 'index.html'
        file.write_text(file.read_text(encoding='utf-8').replace('href="styles.css"', 'href="missing.css"'), encoding='utf-8')
        target = self.directory / 'should-not-exist'
        with self.assertRaisesRegex(ValueError, '引用文件不存在'):
            release.make_release(source, output=target)
        self.assertFalse(target.exists())

    def test_missing_translation_is_reported(self):
        source = self.copy()
        file = source / 'content.js'
        text = file.read_text(encoding='utf-8')
        self.assertIn('contactEmailLabel: "邮箱",', text)
        file.write_text(text.replace('contactEmailLabel: "邮箱",', ''), encoding='utf-8')
        result = release.check_site(source)
        self.assertFalse(result['ok'])
        self.assertTrue(any('zh.contactEmailLabel' in error for error in result['errors']))

    def test_stale_content_hash_reference_is_reported(self):
        source = self.copy()
        with (source / 'app.js').open('a', encoding='utf-8') as file:
            file.write('\n// local test only\n')
        result = release.check_site(source)
        self.assertTrue(any('引用版本与内容哈希不符' in error for error in result['errors']))

    def test_credential_shaped_test_value_is_rejected(self):
        source = self.copy()
        (source / 'test.txt').write_text('AKIA' + 'A' * 16, encoding='utf-8')
        self.assertTrue(any('疑似混入' in error for error in release.check_site(source)['errors']))

    def test_archive_tampering_is_rejected(self):
        archive = self.directory / 'tampered.zip'
        with zipfile.ZipFile(self.base / 'snapshot.zip') as original, zipfile.ZipFile(archive, 'x') as changed:
            for entry in original.infolist():
                data = original.read(entry.filename)
                if entry.filename == 'site/index.html':
                    data += b'<!-- changed -->'
                changed.writestr(entry.filename, data)
        with self.assertRaisesRegex(ValueError, '哈希不一致'):
            release.restore(archive, self.directory / 'tampered-output')
        self.assertFalse((self.directory / 'tampered-output').exists())

    def test_archive_path_traversal_is_rejected_before_writing(self):
        archive = self.directory / 'unsafe.zip'
        data = b'bad'
        manifest = {'schema': 'static-site-release-1', 'files': {'../escape.js': {'sizeBytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}}
        import json
        with zipfile.ZipFile(archive, 'x') as package:
            package.writestr('manifest.json', json.dumps(manifest))
            package.writestr('site/../escape.js', data)
        with self.assertRaisesRegex(ValueError, '不安全路径'):
            release.restore(archive, self.directory / 'unsafe-output')
        self.assertFalse((self.directory / 'escape.js').exists())

    def test_restore_refuses_existing_output_and_dist(self):
        output = self.directory / 'preserve'
        output.mkdir()
        (output / 'marker.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError, '不覆盖'):
            release.restore(self.base / 'snapshot.zip', output)
        self.assertEqual((output / 'marker.txt').read_text(), 'keep')
        with self.assertRaisesRegex(ValueError, '.local/site-releases'):
            release.restore(self.base / 'snapshot.zip', release.ROOT / 'dist')

    def test_delta_upload_contains_only_changed_file_and_refuses_tampering(self):
        source = self.copy()
        (source / 'release-note.txt').write_text('local release test', encoding='utf-8')
        current = release.make_release(source, baseline=self.base, output=self.directory / 'delta')
        self.assertEqual([p.name for p in (current / 'upload').iterdir()], ['release-note.txt'])
        (current / 'upload/release-note.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '拒绝覆盖'):
            release.stage_upload(current)

    def test_upload_refuses_files_outside_change_list(self):
        source = self.copy()
        current = release.make_release(source, baseline=self.base, output=self.directory / 'no-changes')
        (current / 'upload/extra.txt').write_text('unrelated', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '不属于本次变更'):
            release.stage_upload(current)


if __name__ == '__main__':
    unittest.main(verbosity=2)
