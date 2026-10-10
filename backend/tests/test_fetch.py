import hashlib
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import catalog_service, repository_root
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.production.domain.fetch import FetchRequest, FetchToolError
from huavd_map_build.production.north.local.fetch import RegionFetchService
from huavd_map_build.production.south.adapter.workspace.fetch_store import (
    FileSystemFetchStore,
)
from huavd_map_build.shared.kernel import RegionId


class RecordingDownloader:
    def __init__(self, content: bytes, valid_digest: bool = True) -> None:
        self.content = content
        self.valid_digest = valid_digest
        self.calls: list[tuple[str, str, str | None]] = []

    def download(self, url: str, destination: str, limit_rate: str | None) -> None:
        self.calls.append((url, destination, limit_rate))
        target = Path(destination) / url.rsplit("/", 1)[-1]
        if url.endswith(".md5"):
            digest = hashlib.md5(self.content).hexdigest() if self.valid_digest else "0" * 32
            target.write_text(f"{digest.upper()}  guangxi-latest.osm.pbf\n", encoding="ascii")
        else:
            target.write_bytes(self.content)


class RegionFetchServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = catalog_service(repository_root(Path(__file__)))

    def _service(self, downloader: RecordingDownloader) -> RegionFetchService:
        return RegionFetchService(
            self.catalog, downloader, FileSystemFetchStore(), FileDigestAdapter()
        )

    def test_downloads_pbf_and_sidecar_then_accepts_case_insensitive_md5(self) -> None:
        downloader = RecordingDownloader(b"pbf-fixture")
        with tempfile.TemporaryDirectory() as directory:
            output = self._service(downloader).fetch(
                FetchRequest(RegionId("china/guangxi"), directory, "7m")
            )
            content = Path(output).read_bytes()
        self.assertEqual(b"pbf-fixture", content)
        self.assertEqual("7m", downloader.calls[0][2])
        self.assertIsNone(downloader.calls[1][2])
        self.assertTrue(output.endswith("/mirror/guangxi-latest.osm.pbf"))

    def test_digest_mismatch_is_a_tool_failure(self) -> None:
        downloader = RecordingDownloader(b"pbf-fixture", valid_digest=False)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FetchToolError, "md5 check failed"):
                self._service(downloader).fetch(
                    FetchRequest(RegionId("china/guangxi"), directory)
                )

    def test_local_extract_never_downloads_parent_as_district(self) -> None:
        downloader = RecordingDownloader(b"parent-pbf")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "local administrative polygon extract"):
                self._service(downloader).fetch(FetchRequest(
                    RegionId("china/guangxi/guilin/qixing"), directory
                ))
        self.assertEqual([], downloader.calls)
