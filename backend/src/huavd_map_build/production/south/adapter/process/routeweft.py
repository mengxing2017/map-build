"""Bounded, shell-free RouteWeft schema-1 process adapter (POSIX)."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from huavd_map_build.production.south.port.routeweft import RouteWeftError


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class RouteWeftProcess:
    def __init__(self, binary: Path, expected_sha256: str, *, limit: int = 32 * 1024 * 1024,
                 commit: str | None = None, require_build_identity: bool = False):
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise RouteWeftError('ROUTEWEFT_BIN must be an absolute executable file')
        if len(expected_sha256) != 64 or sha256(binary) != expected_sha256:
            raise RouteWeftError('RouteWeft binary SHA-256 mismatch')
        self.binary, self.limit = binary, limit
        self.identity = {'binary_sha256': expected_sha256, 'commit': commit}
        self.require_build_identity = require_build_identity
        self.logs: list[dict] = []

    def call(self, command, arguments, timeout, expected_error=None):
        if sha256(self.binary) != self.identity['binary_sha256']:
            raise RouteWeftError('RouteWeft binary changed')
        started = time.monotonic()
        process = subprocess.Popen([str(self.binary), command, *arguments], shell=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        failure = None
        sampled_peak_rss_kib = None
        with selectors.DefaultSelector() as selector:
            for name, stream in [('stdout', process.stdout), ('stderr', process.stderr)]:
                selector.register(stream, selectors.EVENT_READ, name)
            try:
                while selector.get_map() or process.poll() is None:
                    try:
                        for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
                            if line.startswith('VmHWM:'):
                                sampled_peak_rss_kib = max(sampled_peak_rss_kib or 0, int(line.split()[1]))
                    except (OSError, ValueError):
                        pass  # Optional Linux sampling; process may already have exited.
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise RouteWeftError(f'{command}: outer timeout')
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            target = buffers[key.data]
                            if len(target) + len(chunk) > self.limit:
                                target.extend(chunk[:max(0, self.limit - len(target))])
                                raise RouteWeftError(f'{command}: output limit exceeded')
                            target.extend(chunk)
                process.wait()
            except BaseException as error:
                failure = str(error)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The process may have exited between timeout and kill.
                process.wait()
                raise
            finally:
                process.stdout.close()
                process.stderr.close()
                self.logs.append({'command': command, 'exit_code': process.returncode,
                                  'elapsed_s': time.monotonic() - started, 'failure': failure,
                                  'sampled_peak_rss_kib': sampled_peak_rss_kib,
                                  **{k: bytes(v).decode('utf-8', errors='replace')
                                     for k, v in buffers.items()}})
        try:
            value = json.loads(buffers['stdout'], object_pairs_hook=unique_object,
                               parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (ValueError, UnicodeError) as error:
            raise RouteWeftError(f'{command}: invalid JSON') from error
        if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
            raise RouteWeftError(f'{command}: unsupported schema')
        if expected_error:
            if (process.returncode == 3 and value.get('status') == 'error'
                    and isinstance(value.get('error'), dict)
                    and value['error'].get('kind') == expected_error):
                return value
        elif process.returncode == 0 and value.get('status') == 'ok':
            return value
        raise RouteWeftError(f'{command}: exit/status mismatch or failure: {process.returncode}: {value}',
                             response=value, command=command, exit_code=process.returncode)
