import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from utils.download import hash_updater


def joined(contents):
    """What Rose always made of the hash files: joined by a newline, each
    without its trailing newlines, ending with one"""
    combined = "\n".join(content.decode("utf-8").rstrip("\n") for content in contents)
    if combined and not combined.endswith("\n"):
        combined += "\n"
    return combined.encode("utf-8")


class FakeResponse:
    def __init__(self, content, chunk_sizes, fail=False):
        self.content = content
        self.chunk_sizes = chunk_sizes
        self.fail = fail
        self.headers = {"ETag": f'"{len(content)}"'}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        at = 0
        while at < len(self.content):
            size = next(self.chunk_sizes)
            yield self.content[at:at + size]
            yield b""  # requests yields empty keep-alive chunks too
            at += size
        if self.fail:
            raise requests.ConnectionError("connection reset")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, files, seed=0, fail_on=None):
        self.headers = {}
        self.files = files
        self.random = random.Random(seed)
        self.fail_on = fail_on

    def chunk_sizes(self):
        while True:
            yield self.random.choice((1, 2, 3, 7, 64, 4096))

    def get(self, url, timeout=None, stream=False):
        name = url.rsplit("/", 1)[1]
        return FakeResponse(self.files[name], self.chunk_sizes(), fail=name == self.fail_on)


def hash_files(*contents):
    contents = list(contents) + [b""] * (len(hash_updater.HASH_FILES) - len(contents))
    return dict(zip(hash_updater.HASH_FILES, contents))


class HashFileWriteTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.target = Path(temp_dir.name) / "hashes.game.txt"

    def write(self, files, **session):
        etags = {}
        size = hash_updater.write_hash_files(self.target, FakeSession(files, **session), etags=etags)
        return size, etags

    def test_the_files_are_joined_as_before_whatever_the_chunks(self):
        cases = [
            hash_files(*(b"%016x path/%d.bin\n" % (i, i) * 50 for i in range(9))),
            hash_files(b"a\n\n\n", b"\n\n", b"b", b"c\r\n", b"", b"d\n\nx\n\n"),
            hash_files(b"only one"),
            hash_files(b"a", b"", b"", b"", b"", b"", b"", b"", b""),
            hash_files(),
            hash_files(b"\n"),
            hash_files(*([b"\n\n"] * 9)),
            hash_files(b"", b"", b"", b"", b"", b"", b"", b"", b"last\n"),
        ]
        for files in cases:
            for seed in range(5):
                with self.subTest(files=list(files.values())[:3], seed=seed):
                    size, _ = self.write(files, seed=seed)
                    expected = joined(files.values())
                    self.assertEqual(self.target.read_bytes(), expected)
                    self.assertEqual(size, len(expected))

    def test_each_files_etag_is_recorded(self):
        files = hash_files(*(b"x" * i for i in range(9)))

        _, etags = self.write(files)

        self.assertEqual(etags, {name: f'"{len(content)}"' for name, content in files.items()})

    def test_a_failed_download_keeps_the_file_already_there(self):
        self.target.write_bytes(b"the previous hashes\n")
        files = hash_files(*(b"line %d\n" % i for i in range(9)))

        with self.assertLogs(level="ERROR"), self.assertRaises(hash_updater._DownloadFailed):
            self.write(files, fail_on="hashes.game.txt.4")

        self.assertEqual(self.target.read_bytes(), b"the previous hashes\n")
        self.assertEqual(sorted(p.name for p in self.target.parent.iterdir()), ["hashes.game.txt"])

    def test_update_hash_files_reports_a_failed_download_and_saves_no_state(self):
        files = hash_files(*(b"line %d\n" % i for i in range(9)))
        tools = self.target.parent / "injection" / "tools"
        statuses = []
        with patch.object(hash_updater, "__file__", str(self.target.parent / "utils" / "download" / "hash_updater.py")), \
                patch.object(hash_updater, "check_for_updates", return_value=True), \
                patch.object(hash_updater.requests, "Session", lambda: FakeSession(files, fail_on="hashes.game.txt.8")), \
                patch.object(hash_updater, "save_state") as save_state, \
                self.assertLogs(level="ERROR"):
            self.assertFalse(hash_updater.update_hash_files(statuses.append))

        save_state.assert_not_called()
        self.assertFalse((tools / "hashes.game.txt").exists())
        self.assertIn("Failed to download hashes.game.txt.8", statuses)

    def test_update_hash_files_writes_the_target_and_its_state(self):
        files = hash_files(*(b"line %d\n" % i for i in range(9)))
        tools = self.target.parent / "injection" / "tools"
        with patch.object(hash_updater, "__file__", str(self.target.parent / "utils" / "download" / "hash_updater.py")), \
                patch.object(hash_updater, "check_for_updates", return_value=True), \
                patch.object(hash_updater.requests, "Session", lambda: FakeSession(files)), \
                patch.object(hash_updater, "save_state") as save_state:
            self.assertTrue(hash_updater.update_hash_files())

        self.assertEqual((tools / "hashes.game.txt").read_bytes(), joined(files.values()))
        save_state.assert_called_once_with({"etags": {name: f'"{len(c)}"' for name, c in files.items()}})


if __name__ == "__main__":
    unittest.main()
