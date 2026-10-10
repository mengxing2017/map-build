import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process import native_tools as tools


class NativeToolsTest(unittest.TestCase):
    metadata = json.loads((Path(__file__).resolve().parents[2] / "config/native-renderer.lock.json").read_text())

    def installation(self, path: Path) -> Path:
        (path / "bin").mkdir(parents=True)
        binary = path / "bin/huavd-native-render"
        binary.write_bytes(b"test executable")
        binary.chmod(0o755)
        (path / "binary.sha256").write_text(
            hashlib.sha256(binary.read_bytes()).hexdigest() + "  bin/huavd-native-render\n"
        )
        (path / "build-info.json").write_text(json.dumps(self.metadata))
        (path / "source-lock.json").write_text(json.dumps(self.metadata))
        (path / "licenses").mkdir()
        return binary

    def test_activation_is_stable_and_rejects_corruption_without_changing_old_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.installation(root / "first")
            second = self.installation(root / "second")
            with patch.object(tools, "native_renderer_identity", return_value=json.dumps(self.metadata)), \
                    patch.object(tools, "native_environment", return_value={}), \
                    patch.object(tools.subprocess, "run"):
                tools.activate(first.parent.parent, root / "tools")
                tools.activate(first.parent.parent, root / "tools")
                second.write_bytes(b"corrupted")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    tools.activate(second.parent.parent, root / "tools")
                self.assertEqual(first, (root / "tools/bin/huavd-native-render").resolve())

    def test_self_test_failure_preserves_old_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = self.installation(root / "installation")
            with patch.object(tools, "validate_installation", return_value=binary):
                tools.activate(binary.parent.parent, root / "tools")
            with patch.object(tools, "validate_installation", side_effect=ValueError("self-test failed")):
                with self.assertRaisesRegex(ValueError, "self-test"):
                    tools.activate(root / "other", root / "tools")
            self.assertEqual(binary, (root / "tools/bin/huavd-native-render").resolve())

    def test_archive_rejects_traversal_links_and_duplicate_members(self):
        for kind in ("traversal", "symlink", "hardlink", "duplicate"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive_path = root / "package.tar"
                with tarfile.open(archive_path, "w") as archive:
                    info = tarfile.TarInfo("../outside" if kind == "traversal" else "bin/test")
                    if kind in ("symlink", "hardlink"):
                        info.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                        info.linkname = "../../outside"
                    archive.addfile(info)
                    if kind == "duplicate":
                        archive.addfile(info)
                digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    tools.install_package(archive_path, digest, root / "tools")
                self.assertFalse((root / "outside").exists())

    def test_archive_requires_trusted_matching_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package.tar"
            path.write_bytes(b"bad")
            for digest in ("", "0" * 64):
                with self.assertRaises(ValueError):
                    tools.install_package(path, digest, Path(temporary) / "tools")

    def test_verified_archive_is_installed_and_repeat_install_is_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.installation(root / "source")
            package = root / "package.tar"
            with tarfile.open(package, "w") as archive:
                for child in sorted((root / "source").rglob("*")):
                    archive.add(child, arcname=child.relative_to(root / "source"), recursive=False)
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            with patch.object(tools, "native_renderer_identity", return_value=json.dumps(self.metadata)), \
                    patch.object(tools, "native_environment", return_value={}), \
                    patch.object(tools.subprocess, "run"):
                binary = tools.install_package(package, digest, root / "tools")
                self.assertEqual(binary, tools.install_package(package, digest, root / "tools"))
                self.assertEqual(binary, (root / "tools/bin/huavd-native-render").resolve())
                self.assertEqual(b"test executable", binary.read_bytes())

    def test_different_source_lock_is_rejected_before_self_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.installation(root)
            (root / "source-lock.json").write_text('{}')
            with patch.object(tools, "native_renderer_identity", return_value=json.dumps(self.metadata)):
                with self.assertRaisesRegex(ValueError, "source lock mismatch"):
                    tools.validate_installation(root)

    def test_ambiguous_installations_are_not_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.installation(root / "one")
            self.installation(root / "two")
            with patch.dict(os.environ, {"HUAVD_NATIVE_TOOLS": str(root)}, clear=True), \
                    patch.object(tools, "resolve_renderer", side_effect=ValueError("missing")):
                with self.assertRaisesRegex(ValueError, "unique"):
                    tools.setup()
