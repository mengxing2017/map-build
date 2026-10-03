import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.delivery.domain.checksum_manifest import ChecksumEntry
from huavd_map_build.delivery.north.local.checksum_manifest import ChecksumManifestWriter
from huavd_map_build.delivery.south.adapter.archive.filesystem import FileSystemManifestStore
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter


class ChecksumManifestTest(unittest.TestCase):
    def test_matches_sorted_sha256sum_contract_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "a file.txt").write_bytes(b"alpha")
            (root / "nested/b.txt").write_bytes(b"beta")
            (root / "ignored.sha512").write_text("sidecar", encoding="ascii")
            writer = ChecksumManifestWriter(
                FileSystemManifestStore(), FileDigestAdapter(), AtomicFileWriter()
            )
            manifest = writer.write(
                root=directory,
                output_name="SHA256SUMS",
                algorithm="sha256",
                excluded_names=("SHA512SUMS",),
                excluded_suffixes=(".sha512",),
            )
            verification = subprocess.run(
                ["sha256sum", "-c", "SHA256SUMS"], cwd=root,
                text=True, capture_output=True, check=False,
            )
            content = (root / "SHA256SUMS").read_text(encoding="utf-8")
        expected = (
            f"{hashlib.sha256(b'alpha').hexdigest()}  ./a file.txt\n"
            f"{hashlib.sha256(b'beta').hexdigest()}  ./nested/b.txt\n"
        )
        self.assertEqual(expected, content)
        self.assertEqual(2, len(manifest.entries))
        self.assertEqual(0, verification.returncode, verification.stderr)

    def test_gnu_filename_escaping_is_preserved(self) -> None:
        entry = ChecksumEntry("abc", "./path\\name")
        self.assertEqual("\\abc  ./path\\\\name\n", entry.render())

    def test_overview_mode_includes_sha512_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "map.pmtiles").write_bytes(b"map")
            (root / "map.pmtiles.sha512").write_text("digest\n", encoding="ascii")
            manifest = ChecksumManifestWriter(
                FileSystemManifestStore(), FileDigestAdapter(), AtomicFileWriter()
            ).write(
                root=directory,
                output_name="SHA256SUMS",
                algorithm="sha256",
            )
        self.assertEqual(
            ("./map.pmtiles", "./map.pmtiles.sha512"),
            tuple(entry.path for entry in manifest.entries),
        )
