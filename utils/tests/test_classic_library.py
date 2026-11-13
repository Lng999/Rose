import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.download.repo_downloader import RepoDownloader


class ClassicLibraryTests(unittest.TestCase):
    """LeagueSkins' classic/ folder is kept in %LOCALAPPDATA%/Rose/classic
    (the sync itself is tested in test_skin_sync)"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.downloader = RepoDownloader(target_dir=self.root / 'skins')
        self.classic_dir = self.root / 'classic'

    def test_classic_folder_sits_next_to_the_skins(self):
        self.assertEqual(self.downloader.classic_dir, self.classic_dir)
        self.assertEqual(
            self.downloader._resolve_local_path('classic/1/1001/1001.fantome'),
            self.classic_dir / '1' / '1001' / '1001.fantome',
        )
        self.assertIsNone(self.downloader._resolve_local_path('classic/../outside.fantome'))

    def test_a_path_leaving_its_folder_is_skipped(self):
        for path in (
            'skins/../outside.zip',
            'skins/1/../../outside.zip',
            'skins/1\\..\\..\\outside.zip',
            'resources/../skins/1/1001/1001.zip',
            'skins/C:/Windows/evil.zip',
            'skins//server/share/evil.zip',
        ):
            with self.subTest(path=path), self.assertLogs(level='WARNING'):
                self.assertIsNone(self.downloader._resolve_local_path(path))

    def test_paths_are_checked_without_reading_the_disk(self):
        # resolve() opened every path of the library, twice per sync: 5 s for
        # each pass over 11,000 files
        with patch.object(Path, 'resolve', side_effect=AssertionError('resolve() reads the disk')):
            self.assertEqual(
                self.downloader._resolve_local_path('skins/1/1001/1001.zip'),
                self.root / 'skins' / '1' / '1001' / '1001.zip',
            )
            self.assertIsNone(self.downloader._resolve_local_path('skins/../outside.zip'))

    def test_a_library_in_its_own_folder_keeps_its_resources_there(self):
        self.assertEqual(self.downloader.resources_dir, self.root / 'resources')
        self.assertIsNone(self.downloader._resolve_local_path('README.md'))


if __name__ == '__main__':
    unittest.main()
