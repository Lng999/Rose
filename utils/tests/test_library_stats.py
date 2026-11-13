import tempfile
import unittest
from pathlib import Path

from utils.download.repo_downloader import RepoDownloader


class LibraryStatsTests(unittest.TestCase):
    """The counts logged before and after the skin sync"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.skins = Path(temp_dir.name) / "skins"
        self.downloader = RepoDownloader(target_dir=self.skins)

    def add(self, relative):
        path = self.skins / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def test_skins_chromas_and_previews_are_counted(self):
        self.add("1/1001/1001.zip")
        self.add("1/1001/1001.png")
        self.add("1/1001/1002/1002.zip")
        self.add("1/1001/1002/1002.png")
        self.add("1/1001/1003/1003.fantome")
        self.add("1/1004/1004.fantome")
        self.add("2/2001/2001.ZIP")  # Windows names are case-insensitive
        self.add("2/2002/2002.png")  # a preview without its skin
        # Not skins: a folder without an id, another file, a misplaced archive
        self.add("2/notes/notes.zip")
        self.add("2/2001/readme.txt")
        self.add("2/2001/2009/2001.zip")
        self.add(".skin_sync_state.json")

        self.assertEqual(self.downloader.get_detailed_stats(), {
            "total_skins": 3, "total_chromas": 2, "total_ids": 5, "total_previews": 3,
        })

    def test_a_missing_library_counts_nothing(self):
        self.assertEqual(self.downloader.get_detailed_stats(), {
            "total_skins": 0, "total_chromas": 0, "total_ids": 0, "total_previews": 0,
        })


if __name__ == "__main__":
    unittest.main()
