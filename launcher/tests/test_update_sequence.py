import configparser
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import read_config_file, write_config_file
from launcher.update import update_sequence
from launcher.update.update_sequence import UpdateSequence

RUNNING = "1.1.10"


class UpdateRetryTests(unittest.TestCase):
    """An update whose files never get copied (robocopy failing on a locked
    file...) leaves Rose on its old version with a newer installed_version:
    it is retried a few times, then given up until a newer release"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.config_path = self.root / "config.ini"
        self.remote = "1.2.0"
        self.downloads = []

        for target, value in (
            ("get_config_file_path", lambda: self.config_path),
            ("APP_VERSION", RUNNING),
        ):
            patcher = patch.object(update_sequence, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sequence(self):
        sequence = UpdateSequence()
        release = {"tag_name": self.remote}
        asset = {"name": f"update_package_{self.remote}.zip", "browser_download_url": "https://example.invalid/u.zip", "size": 1}
        sequence.github_client.get_latest_release = lambda: release
        sequence.github_client.get_zip_asset = lambda _release: asset

        def download(url, zip_path, *_args):
            self.downloads.append(self.remote)
            return True

        sequence.downloader.download_update = download
        sequence.installer.extract_update = lambda *_args: self.root / "staging"
        # The script starts, then fails to copy the files once Rose has exited
        sequence.installer.install = lambda *_args: True
        return sequence

    def start_rose(self):
        """One start of a Rose that stays on RUNNING whatever it installs"""
        updated = self.sequence().perform_update(lambda _status: None, lambda _progress: None)
        if not updated:
            # What initialize_core_components does once the launcher let Rose start
            self.set_option("installed_version", RUNNING)
        return updated

    def config(self):
        config = configparser.ConfigParser()
        read_config_file(config, self.config_path)
        return config

    def set_option(self, option, value):
        config = self.config()
        if not config.has_section("General"):
            config.add_section("General")
        config.set("General", option, value)
        write_config_file(config, self.config_path)

    def test_a_release_that_never_installs_is_given_up_after_the_retries(self):
        results = [self.start_rose() for _ in range(10)]

        # The first attempt, then three retries, then Rose starts on its old
        # version for good: it used to download the release again forever,
        # skipping one start in four
        self.assertEqual(results, [True] * 4 + [False] * 6)
        self.assertEqual(self.downloads, ["1.2.0"] * 4)
        self.assertEqual(self.config().get("General", "update_failed_version"), "1.2.0")

    def test_a_newer_release_is_tried_after_one_was_given_up(self):
        for _ in range(5):
            self.start_rose()
        self.downloads.clear()

        self.remote = "1.2.1"
        self.assertTrue(self.start_rose())
        self.assertEqual(self.downloads, ["1.2.1"])

        # Its own failure gets its own retries
        self.assertEqual([self.start_rose() for _ in range(4)], [True, True, True, False])
        self.assertEqual(self.config().get("General", "update_failed_version"), "1.2.1")

    def test_an_update_that_installs_needs_no_retry(self):
        self.assertTrue(self.start_rose())
        self.assertEqual(self.config().get("General", "installed_version"), "1.2.0")

        # The copy worked: Rose now runs the release it downloaded
        with patch.object(update_sequence, "APP_VERSION", "1.2.0"):
            self.assertFalse(self.sequence().perform_update(lambda _status: None, lambda _progress: None))
        self.assertEqual(self.downloads, ["1.2.0"])
        self.assertFalse(self.config().has_option("General", "update_failed_version"))


if __name__ == "__main__":
    unittest.main()
