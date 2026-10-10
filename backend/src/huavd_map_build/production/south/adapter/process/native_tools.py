"""Install and locate an audited Native executable without exposing digest paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from huavd_map_build.production.south.adapter.process.raster_native import (
    native_environment, native_renderer_identity,
)


def tools_root() -> Path:
    return Path(os.environ.get("HUAVD_NATIVE_TOOLS", str(
        Path(os.environ.get("HUAVD_MAP_BUILD_HOME", "/tmp/huavd-map-build"))
        / "tools/maplibre-native"
    ))).expanduser().resolve()


def resolve_renderer() -> str:
    explicit = os.environ.get("HUAVD_NATIVE_RENDER_BIN")
    if explicit:
        path = shutil.which(explicit)
        if path is None:
            raise ValueError(f"Native executable does not exist: {explicit}")
        return str(Path(path).resolve())
    stable = tools_root() / "bin/huavd-native-render"
    if stable.is_file() and os.access(stable, os.X_OK):
        return str(stable.resolve())
    installed = shutil.which("huavd-native-render")
    if installed:
        return str(Path(installed).resolve())
    raise ValueError("Native renderer missing; run make setup (see Native tool source configuration)")


def validate_installation(directory: Path) -> Path:
    directory = directory.resolve()
    binary = directory / "bin/huavd-native-render"
    required = ("build-info.json", "binary.sha256", "source-lock.json", "licenses")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"Native executable missing or not executable: {binary}")
    for name in required:
        if not (directory / name).exists():
            raise ValueError(f"Native installation missing {name}: {directory}")
    checksum = (directory / "binary.sha256").read_text().split()
    with binary.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if len(checksum) != 2 or checksum[1] != "bin/huavd-native-render" or checksum[0] != actual:
        raise ValueError("Native installation binary checksum mismatch")
    metadata = json.loads(native_renderer_identity(str(binary)))
    recorded = json.loads((directory / "build-info.json").read_text())
    lock = json.loads((Path(__file__).resolve().parents[7] / "config/native-renderer.lock.json").read_text())
    source_lock = json.loads((directory / "source-lock.json").read_text())
    for key in ("protocol_version", "wrapper_revision", "core_revision", "backend"):
        if metadata.get(key) != lock[key] or source_lock.get(key) != lock[key]:
            raise ValueError(f"Native source lock mismatch: {key}")
    if any(metadata.get(key) != value for key, value in recorded.items()):
        raise ValueError("Native build-info does not match executable")
    subprocess.run([str(binary), "--self-test"], env=native_environment(),
                   check=True, timeout=120)
    return binary


def activate(directory: Path, root: Path) -> Path:
    binary = validate_installation(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)
    # Never publish an unvalidated version or overwrite an arbitrary directory.
    stable = root / "bin/huavd-native-render"
    if stable.exists() and not stable.is_symlink():
        raise ValueError(f"Refusing to overwrite non-link: {stable}")
    with tempfile.TemporaryDirectory(prefix=".activate-", dir=root) as temporary:
        link = Path(temporary) / "renderer"
        link.symlink_to(binary)
        link.replace(stable)
    return binary


def install_package(package: Path, expected: str, root: Path) -> Path:
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("Set HUAVD_NATIVE_PACKAGE_SHA256 to the trusted publisher SHA-256")
    # Hash and extract the same open file, so path replacement cannot bypass verification.
    root.mkdir(parents=True, exist_ok=True)
    with package.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("Native runtime package checksum mismatch")
        stream.seek(0)
        with tempfile.TemporaryDirectory(prefix=".package-", dir=root) as temporary:
            staging = Path(temporary)
            with tarfile.open(fileobj=stream, mode="r:*") as archive:
                members = archive.getmembers()
                names: set[str] = set()
                for member in members:
                    name = Path(member.name)
                    if (name.is_absolute() or ".." in name.parts or member.issym()
                            or member.islnk() or not (member.isfile() or member.isdir())
                            or member.name in names):
                        raise ValueError(f"Unsafe Native package member: {member.name}")
                    names.add(member.name)
                archive.extractall(staging, members=members, filter="data")
            # Package layout is fixed: bin/, licenses/, build-info.json, etc. at root.
            validate_installation(staging)
            destination = root / expected
            if destination.exists():
                validate_installation(destination)
            else:
                staging.rename(destination)
            return activate(destination, root)


def setup() -> Path:
    root = tools_root()
    source = os.environ.get("HUAVD_NATIVE_INSTALLATION")
    package = os.environ.get("HUAVD_NATIVE_PACKAGE")
    if source and package:
        raise ValueError("Choose an existing Native installation OR a runtime package")
    if source:
        return activate(Path(source), root)
    if package:
        return install_package(Path(package), os.environ.get("HUAVD_NATIVE_PACKAGE_SHA256", ""), root)
    try:
        binary = Path(resolve_renderer())
    except ValueError:
        candidates = sorted(root.glob("*/bin/huavd-native-render"))
        if len(candidates) != 1:
            raise ValueError(
                "No unique Native installation. Maintainer: configure HUAVD_NATIVE_INSTALLATION "
                "or HUAVD_NATIVE_PACKAGE + HUAVD_NATIVE_PACKAGE_SHA256 once, then run make setup. "
                "No automatic source build or download was attempted."
            ) from None
        binary = candidates[0]
    return activate(binary.parent.parent, root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "check", "resolve"))
    args = parser.parse_args()
    try:
        if args.action == "setup":
            binary = setup()
        else:
            binary = Path(resolve_renderer())
            if args.action == "check":
                validate_installation(binary.parent.parent)
        print(binary)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Native: {error}\n")


if __name__ == "__main__":
    main()
