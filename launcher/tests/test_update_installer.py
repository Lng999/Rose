import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from launcher.update.update_installer import UpdateInstaller


def make_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class ExtractUpdateTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.archive = self.root / "update_package_1.2.3.zip"
        self.staging = self.root / "staging"
        self.statuses = []
        self.progress = []

    def extract(self):
        return UpdateInstaller().extract_update(
            self.archive, self.staging, self.progress.append, self.statuses.append
        )

    def test_the_package_is_extracted_under_its_root_folder(self):
        make_zip(self.archive, {
            "Rose/Rose.exe": b"exe",
            "Rose/_internal/python312.dll": b"dll",
            "Rose/Pengu Loader/plugins/ROSE-UI/index.js": b"js",
        })

        root = self.extract()

        self.assertEqual(root, self.staging / "Rose")
        self.assertEqual((root / "Rose.exe").read_bytes(), b"exe")
        self.assertEqual((root / "_internal" / "python312.dll").read_bytes(), b"dll")
        self.assertEqual((root / "Pengu Loader" / "plugins" / "ROSE-UI" / "index.js").read_bytes(), b"js")
        self.assertEqual(self.progress[-1], 60)
        self.assertEqual(self.progress, sorted(self.progress))

    def test_the_archive_is_opened_once_whatever_its_size(self):
        # Reopening the package for every member took 11s for a 1,166-file
        # build, against half a second when it is opened once
        make_zip(self.archive, {f"Rose/_internal/file{i}.pyd": b"x" for i in range(50)})

        with patch("launcher.update.update_installer.zipfile.ZipFile", wraps=zipfile.ZipFile) as opened:
            root = self.extract()

        self.assertEqual(opened.call_count, 1)
        self.assertEqual(len(list((root / "_internal").iterdir())), 50)

    def test_a_path_leaving_the_staging_folder_is_refused_before_anything_is_written(self):
        make_zip(self.archive, {
            "Rose/Rose.exe": b"exe",
            "../escaped.txt": b"evil",
        })

        with self.assertLogs(level="ERROR"):
            root = self.extract()

        self.assertIsNone(root)
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertEqual(list(self.staging.iterdir()), [])
        self.assertTrue(any(status.startswith("Extraction failed") for status in self.statuses))

    def test_a_package_with_loose_files_is_its_own_root(self):
        make_zip(self.archive, {"Rose.exe": b"exe", "_internal/base_library.zip": b"lib"})

        self.assertEqual(self.extract(), self.staging)

    def test_an_empty_package_is_invalid(self):
        make_zip(self.archive, {})

        self.assertIsNone(self.extract())
        self.assertIn("Invalid update package", self.statuses)


if __name__ == "__main__":
    unittest.main()
