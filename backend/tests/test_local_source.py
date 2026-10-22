import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huavd_map_build.bootstrap import catalog_service, repository_root
from huavd_map_build.delivery.north.local.source import (
    _md5,
    raster_source_revision,
    resolve_source,
    source_revision,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


class LocalSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = catalog_service(repository_root(Path(__file__)))
        self.date = BuildDate("20261021")

    def resolve(self, region, workdir, input_name="input.osm.pbf", content=b"local-pbf"):
        root = Path(workdir)
        manual = root / "manual" / input_name
        manual.parent.mkdir(parents=True, exist_ok=True)
        manual.write_bytes(content)
        session = SessionId(f"{region.replace('/', '-')}-20261021")
        staged = root / "staging" / session.value / "source.osm.pbf"
        staged.parent.mkdir(parents=True)
        staged.symlink_to(manual)
        return resolve_source(
            self.catalog, region=RegionId(region), workdir=workdir, session=session
        )

    def test_local_input_without_catalog_source_is_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.resolve("china/taiwan/taipei", directory, "taipei.osm.pbf")
            self.assertEqual(("local", None), (source.vendor, source.url))
            self.assertEqual("taipei.osm.pbf", source.basename)
            self.assertEqual(len(b"local-pbf"), source.evidence.size_bytes)
            self.assertIsNone(source.evidence.md5)
            self.assertEqual(
                "local-taipei-2026-10-21",
                source_revision(
                    source, RegionId("china/taiwan/taipei"), self.date, Role.BASE
                ),
            )
            self.assertEqual(
                "local-taipei-2026-10-21",
                source_revision(
                    source, RegionId("china/taiwan/taipei"), self.date,
                    Role.RASTER_BAKE,
                ),
            )

    def test_local_input_ignores_stale_mirror_md5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirror = root / "mirror/guangxi-latest.osm.pbf"
            mirror.parent.mkdir()
            mirror.write_bytes(b"mirror-pbf")
            Path(f"{mirror}.md5").write_text(
                f"{'0' * 32}  guangxi-latest.osm.pbf\n", encoding="ascii"
            )
            source = self.resolve("china/guangxi", directory, "guangxi-260726.osm.pbf")
            self.assertEqual(("local", None), (source.vendor, source.url))
            self.assertEqual("guangxi-260726.osm.pbf", source.basename)
            self.assertIsNone(source.evidence.md5)
            self.assertEqual(
                "local-guangxi-260726-2026-10-21",
                source_revision(
                    source, RegionId("china/guangxi"), self.date, Role.BASE
                ),
            )
            self.assertEqual(
                "local-guangxi-260726-2026-10-21",
                source_revision(
                    source, RegionId("china/guangxi"), self.date,
                    Role.RASTER_BAKE,
                ),
            )

    def test_local_input_reads_its_own_md5_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / "manual/guangxi-260726.osm.pbf"
            manual.parent.mkdir(parents=True)
            manual.write_bytes(b"local-extract")
            digest = hashlib.md5(manual.read_bytes()).hexdigest()
            Path(f"{manual}.md5").write_text(
                f"{digest}  guangxi-260726.osm.pbf\n", encoding="ascii"
            )
            session = SessionId("china-guangxi-20261021")
            staged = root / "staging" / session.value / "source.osm.pbf"
            staged.parent.mkdir(parents=True)
            staged.symlink_to(manual)
            source = resolve_source(
                self.catalog, region=RegionId("china/guangxi"),
                workdir=directory, session=session,
            )
            self.assertEqual(("local", None), (source.vendor, source.url))
            self.assertEqual(digest, source.evidence.md5)

    def test_catalog_input_uses_mirror_md5_and_geofabrik_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirror = root / "mirror/guangxi-latest.osm.pbf"
            mirror.parent.mkdir()
            mirror.write_bytes(b"mirror-pbf")
            digest = hashlib.md5(mirror.read_bytes()).hexdigest()
            Path(f"{mirror}.md5").write_text(
                f"{digest}  guangxi-latest.osm.pbf\n", encoding="ascii"
            )
            session = SessionId("china-guangxi-20261021")
            staged = root / "staging" / session.value / "source.osm.pbf"
            staged.parent.mkdir(parents=True)
            staged.symlink_to(mirror)
            source = resolve_source(
                self.catalog, region=RegionId("china/guangxi"),
                workdir=directory, session=session,
            )
            self.assertEqual("geofabrik", source.vendor)
            self.assertEqual(self.catalog.pbf_url(RegionId("china/guangxi")), source.url)
            self.assertEqual(digest, source.evidence.md5)
            self.assertEqual(
                "geofabrik-guangxi-2026-10-21",
                source_revision(source, RegionId("china/guangxi"), self.date, Role.BASE),
            )
            self.assertEqual(
                "geofabrik-guangxi-2026-10-21",
                source_revision(
                    source, RegionId("china/guangxi"), self.date, Role.RASTER_BAKE
                ),
            )

    def test_catalog_input_keeps_basename_stem_for_raster_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirror = root / "mirror/tibet-latest.osm.pbf"
            mirror.parent.mkdir()
            mirror.write_bytes(b"mirror-pbf")
            session = SessionId("china-xizang-20261021")
            staged = root / "staging" / session.value / "source.osm.pbf"
            staged.parent.mkdir(parents=True)
            staged.symlink_to(mirror)
            source = resolve_source(
                self.catalog, region=RegionId("china/xizang"),
                workdir=directory, session=session,
            )
            self.assertEqual("geofabrik", source.vendor)
            self.assertEqual(
                "geofabrik-xizang-2026-10-21",
                source_revision(
                    source, RegionId("china/xizang"), self.date, Role.BASE
                ),
            )
            self.assertEqual(
                "geofabrik-tibet-2026-10-21",
                source_revision(
                    source, RegionId("china/xizang"), self.date, Role.RASTER_BAKE
                ),
            )

    def test_md5_rejects_invalid_or_incorrect_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.pbf"
            target.write_bytes(b"input")
            sidecar = Path(f"{target}.md5")
            digest = hashlib.md5(b"input").hexdigest()
            for record in ("", "not-a-checksum", "0" * 32,
                           f"{digest}\n{digest}\n", f"{digest}junk"):
                with self.subTest(record=record):
                    sidecar.write_text(record)
                    with self.assertRaisesRegex(ValueError, "MD5"):
                        _md5(sidecar, target)
            sidecar.write_text(f"{digest.upper()}  *ignored-name.pbf\n")
            self.assertEqual(digest, _md5(sidecar, target))
            sidecar.write_text(digest)
            self.assertEqual(digest, _md5(sidecar, target))

    def test_md5_rejects_broken_link_directory_and_unreadable_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.pbf"
            target.write_bytes(b"input")
            sidecar = Path(f"{target}.md5")
            self.assertIsNone(_md5(sidecar, target))
            sidecar.symlink_to(Path(directory) / "missing")
            with self.assertRaisesRegex(ValueError, "MD5 sidecar"):
                _md5(sidecar, target)
            sidecar.unlink()
            sidecar.mkdir()
            with self.assertRaisesRegex(ValueError, "MD5 sidecar"):
                _md5(sidecar, target)
            sidecar.rmdir()
            sidecar.write_text(hashlib.md5(b"input").hexdigest())
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(ValueError, "cannot verify MD5"):
                    _md5(sidecar, target)

    def test_md5_rejects_input_changed_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.pbf"
            target.write_bytes(b"input")
            sidecar = Path(f"{target}.md5")
            sidecar.write_text(hashlib.md5(b"input").hexdigest())
            original_md5 = hashlib.md5

            def changed_digest():
                digest = original_md5()
                class ChangingDigest:
                    def update(self, chunk):
                        digest.update(chunk)
                        target.write_bytes(b"changed input")

                    def hexdigest(self):
                        return digest.hexdigest()

                return ChangingDigest()

            with patch(
                "huavd_map_build.delivery.north.local.source.hashlib.md5",
                side_effect=changed_digest,
            ):
                with self.assertRaisesRegex(ValueError, "changed while reading"):
                    _md5(sidecar, target)

    def test_geofabrik_raster_requires_own_catalog_basename(self) -> None:
        from unittest.mock import Mock

        catalog = Mock()
        catalog.region.return_value.geofabrik.basename = None
        manifest = {
            "source": {"vendor": "geofabrik", "url": "https://example.test/region.pbf"},
            "huavd_record": {"source_revision": "geofabrik-taipei-2026-10-21"},
        }
        with self.assertRaisesRegex(ValueError, "requires own catalog basename"):
            raster_source_revision(catalog, manifest, RegionId("china/taiwan/taipei"), self.date)


if __name__ == "__main__":
    unittest.main()
