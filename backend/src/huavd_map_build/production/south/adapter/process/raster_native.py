"""Native protocol boundary; no native library is loaded into the Python process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import threading
import zlib

from huavd_map_build.production.domain.raster import RasterExecutionError, RasterNonRetryableError
from huavd_map_build.production.south.adapter.process.raster import _environment, _executable


def native_environment() -> dict[str, str]:
    allowed = ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "LD_LIBRARY_PATH", "UV_USE_IO_URING")
    extra = {key: os.environ[key] for key in allowed if key in os.environ}
    extra.setdefault("UV_USE_IO_URING", "0")
    if not extra.get("VK_DRIVER_FILES") and not extra.get("VK_ICD_FILENAMES"):
        profile = Path(os.environ.get("HUAVD_NATIVE_PROFILE", str(
            Path(__file__).resolve().parents[7] / ".devbox/nix/profile/default"
        )))
        icd = profile / "share/vulkan/icd.d/lvp_icd.x86_64.json"
        loader = profile / "lib/libvulkan.so.1"
        if icd.is_file() and loader.is_file():
            driver = Path(json.loads(icd.read_text())["ICD"]["library_path"])
            if not driver.is_absolute() or not driver.is_file():
                raise RasterExecutionError(f"Invalid Vulkan software driver: {driver}")
            extra["VK_DRIVER_FILES"] = str(icd)
            extra["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (
                str(loader.resolve().parent), str(driver.parent), extra.get("LD_LIBRARY_PATH"),
            )))
    return _environment(extra)


def native_renderer_identity(command: str) -> str:
    executable = _executable(command)
    try:
        result = subprocess.run(
            [executable, "--version"], env=native_environment(), capture_output=True,
            text=True, timeout=10, check=False,
        )
        metadata = json.loads(result.stdout)
        if (
            result.returncode != 0 or not isinstance(metadata, dict)
            or metadata.get("protocol_version") != 1
            or metadata.get("engine") != "maplibre-native-headless"
            or metadata.get("backend") != "vulkan"
        ):
            raise ValueError("unsupported native renderer protocol")
        for name in ("wrapper_patch_sha256", "source_sha256"):
            value = metadata.get(name, "")
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"missing native build provenance: {name}")
        with open(executable, "rb") as binary:
            metadata["binary_sha512"] = hashlib.file_digest(binary, "sha512").hexdigest()
        environment = native_environment()
        runtime = {key: environment[key] for key in (
            "VK_DRIVER_FILES", "VK_ICD_FILENAMES", "LD_LIBRARY_PATH", "UV_USE_IO_URING"
        ) if key in environment}
        # Immutable Nix library paths and explicit ICD contents enter cache identity.
        for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES"):
            if name in runtime:
                runtime[f"{name}_sha256"] = ":".join(
                    hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for path in runtime[name].split(os.pathsep)
                )
        metadata["runtime"] = runtime
        return json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise RasterExecutionError(f"native renderer identity check failed: {error}") from error


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The group may still contain children after its leader has exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


class NativeProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[bytes]] = set()
        self._cancelled = False

    def add(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._cancelled:
                raise RasterNonRetryableError("native batch has been cancelled")
            self._processes.add(process)

    def remove(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.discard(process)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            for process in self._processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def run_native(arguments: list[str], timeout_seconds: int, registry: NativeProcessRegistry | None = None) -> None:
    try:
        process = subprocess.Popen(
            arguments, env=native_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    except OSError as error:
        raise RasterNonRetryableError(f"failed to start native renderer: {error}") from error
    tail = bytearray()

    def drain() -> None:
        assert process.stdout is not None
        while block := process.stdout.read(8192):
            tail.extend(block)
            del tail[:-65536]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        if registry is not None:
            registry.add(process)
        try:
            code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise RasterExecutionError(f"native renderer timed out after {timeout_seconds}s") from error
        reader.join(timeout=1)
        if reader.is_alive():
            raise RasterExecutionError("native renderer left a child holding its output pipe")
        if code != 0:
            diagnostic = tail.decode("utf-8", errors="replace")
            error_type = RasterNonRetryableError if code in (2, 3, 4, 7, 126, 127) else RasterExecutionError
            error = error_type(f"native renderer failed with exit code {code}: {diagnostic}")
            error.exit_code = code
            raise error
    finally:
        if registry is not None:
            registry.remove(process)
        _stop_group(process)
        reader.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if "--output" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            output.with_name(f".{output.name}.native-{process.pid}.png").unlink(missing_ok=True)


def validate_native_png(path: str, size: int) -> None:
    """Check the complete non-interlaced RGBA8 PNG emitted by our CLI."""
    try:
        target = Path(path)
        if target.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("PNG exceeds size limit")
        payload = target.read_bytes()
        if payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("invalid PNG signature")
        offset, compressed, header, ended = 8, bytearray(), False, False
        while offset < len(payload):
            length = struct.unpack_from(">I", payload, offset)[0]
            kind = payload[offset + 4:offset + 8]
            end = offset + 12 + length
            if end > len(payload):
                raise ValueError("truncated PNG chunk")
            content = payload[offset + 8:offset + 8 + length]
            checksum = struct.unpack_from(">I", payload, offset + 8 + length)[0]
            if zlib.crc32(kind + content) != checksum:
                raise ValueError("PNG checksum mismatch")
            if not header:
                if kind != b"IHDR" or length != 13:
                    raise ValueError("missing PNG header")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", content)
                if (width, height, depth, color, compression, filtering, interlace) != (size, size, 8, 6, 0, 0, 0):
                    raise ValueError("unexpected PNG dimensions or encoding")
                header = True
            elif kind == b"IDAT":
                compressed.extend(content)
            elif kind == b"IEND":
                if length != 0 or end != len(payload):
                    raise ValueError("invalid PNG end")
                ended = True
            offset = end
        decoder = zlib.decompressobj()
        expected = size * (size * 4 + 1)
        pixels = decoder.decompress(compressed, expected + 1)
        if not ended or not decoder.eof or decoder.unused_data or len(pixels) != expected:
            raise ValueError("incomplete PNG pixel stream")
        if any(pixels[row * (size * 4 + 1)] > 4 for row in range(size)):
            raise ValueError("invalid PNG row filter")
    except (OSError, ValueError, struct.error, zlib.error) as error:
        raise RasterNonRetryableError(f"invalid native PNG {path}: {error}") from error
