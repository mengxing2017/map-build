"""Explicit, offline local source setup; regular builds never fetch tools."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone

from huavd_map_build.production.south.adapter.process.routeweft import RouteWeftProcess, sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError
from huavd_map_build.production.south.adapter.process.routeweft_contract import capabilities, build_report


def ensure_rust_toolchain(source: Path):
    if shutil.which('rustup') is None:
        raise RouteWeftError('rustup is required to install the locked RouteWeft toolchain; '
                             'run setup inside devbox shell (devbox provides rustup)')
    specification = tomllib.loads((source / 'rust-toolchain.toml').read_text())['toolchain']
    channel = specification['channel']
    installed = subprocess.check_output(['rustup', 'toolchain', 'list'], text=True)
    if not any(line.split()[0] == channel or line.split()[0].startswith(channel + '-')
               for line in installed.splitlines() if line.split()):
        subprocess.run(['rustup', 'toolchain', 'install', channel,
                        '--profile', specification.get('profile', 'minimal')], check=True)
    return channel


def installation_target(root: Path, commit: str) -> Path:
    """Tool installations belong to the project, independently of map workspaces."""
    base = Path(os.environ.get('HUAVD_TOOLS_DIR', str(root / 'tools'))).expanduser().resolve()
    return Path(os.environ.get('ROUTEWEFT_TOOLS', str(base / 'routeweft'))).expanduser().resolve() / commit


def setup(root: Path, workdir: Path, source: Path | None):
    lock = json.loads((root / 'config/routeweft.lock.json').read_text())
    target = installation_target(root, lock['commit'])
    receipt_path = target / 'receipt.json'
    if receipt_path.exists():
        try:
            process, receipt = receipt_process(target / 'routeweft', receipt_path, lock)
            doctor(process)
        except (OSError, ValueError, KeyError, TypeError, RouteWeftError) as error:
            print(f'RouteWeft: cached installation invalid; rebuilding: {error}', file=sys.stderr)
        else:
            print(f'RouteWeft: reusing verified installation {target}', file=sys.stderr)
            return receipt
    if source is None:
        cache = target.parent / 'sources'
        cache.mkdir(parents=True, exist_ok=True)
        source = Path(tempfile.mkdtemp(prefix=lock['commit'] + '-', dir=cache))
        subprocess.run(['git', 'init', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1',
                        lock['repository'], lock['commit']], check=True)
        subprocess.run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    source = source.resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != lock['commit'] or git('status', '--porcelain', '--untracked-files=normal'):
        raise RouteWeftError('setup requires a clean checkout of the locked commit')
    channel = ensure_rust_toolchain(source)
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rustup', 'run', channel, *lock['build'],
                    '--target-dir', str(target / 'target')], cwd=source, check=True,
                   env={key: value for key, value in os.environ.items()
                        if key not in ('ROUTEWEFT_BUILD_COMMIT', 'ROUTEWEFT_BUILD_SOURCE_DIRTY',
                                       'ROUTEWEFT_BUILD_SOURCE_KIND')})
    binary = target / 'routeweft'
    temporary = target / 'routeweft.new'
    shutil.copyfile(target / 'target/release/routeweft', temporary)
    temporary.chmod(0o755)
    checked = doctor(RouteWeftProcess(temporary, sha256(temporary), commit=lock['commit'],
                                     require_build_identity=lock.get('require_build_identity', False)))
    os.replace(temporary, binary)
    receipt = {'schema': 1, 'commit': lock['commit'], 'binary_sha256': sha256(binary),
               'platform': platform.platform(), 'cargo_lock_sha256': sha256(source / 'backend/Cargo.lock'),
               'toolchain': subprocess.check_output(['rustup', 'run', channel, 'rustc', '--version'],
                                                  cwd=source, text=True).strip(),
               'built_at': datetime.now(timezone.utc).isoformat(),
               'build_identity': checked['capabilities'].get('build')}
    receipt_tmp = target / 'receipt.json.new'
    receipt_tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    os.replace(receipt_tmp, target / 'receipt.json')
    return receipt


def tool(root: Path, workdir: Path):
    lock = json.loads((root / 'config/routeweft.lock.json').read_text())
    target = installation_target(root, lock['commit'])
    binary = Path(os.environ.get('ROUTEWEFT_BIN', str(target / 'routeweft')))
    expected = os.environ.get('ROUTEWEFT_SHA256')
    receipt_path = Path(os.environ.get('ROUTEWEFT_RECEIPT', str(target / 'receipt.json')))
    if expected:
        return RouteWeftProcess(binary, expected,
                               require_build_identity=lock.get('require_build_identity', False))
    if not receipt_path.is_file():
        raise RouteWeftError(
            f'RouteWeft installation receipt not found: {receipt_path}. '
            'Run make setup-routeweft in the project, then retry. Tool roots can be overridden through '
            'HUAVD_TOOLS_DIR or ROUTEWEFT_TOOLS. '
            'For an explicitly supplied ROUTEWEFT_BIN, provide its trusted '
            'ROUTEWEFT_SHA256 or ROUTEWEFT_RECEIPT.')
    process, _ = receipt_process(binary, receipt_path, lock)
    return process


def receipt_process(binary: Path, receipt_path: Path, lock: dict):
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('schema') != 1 or receipt.get('commit') != lock['commit']:
        raise RouteWeftError('receipt does not match tool lock')
    for key in ('platform', 'toolchain', 'cargo_lock_sha256', 'built_at'):
        if not receipt.get(key):
            raise RouteWeftError(f'missing receipt {key}')
    return RouteWeftProcess(binary, receipt['binary_sha256'], commit=lock['commit'],
                            require_build_identity=lock.get('require_build_identity', False)), receipt


def doctor(process, probe: Path | None = None):
    # A caller-supplied tiny PBF is explicit: no downloads and no renderer dependencies.
    version = capabilities(process)
    with tempfile.TemporaryDirectory(prefix='routeweft-probe-') as directory:
        if probe is None:
            from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
            probe = Path(directory) / 'probe.osm.pbf'
            generate(probe)
        output = Path(directory) / 'dataset'
        preflight = process.call('preflight', ['--input', str(probe.resolve()), '--profile', 'driving',
                                             '--invalid-restrictions', 'reject', '--json'], 60)
        report = build_report(preflight, sha256(probe), 'reject')
        built = process.call('build', ['--input', str(probe.resolve()), '--profile', 'driving',
                                      '--invalid-restrictions', 'reject', '--output', str(output)], 60)
        verified = process.call('verify', ['--dataset', str(output), '--json'], 30)
        manifest = verified.get('manifest', {})
        if (verified.get('verified') is not True or built.get('manifest') != manifest
                or manifest.get('format') != 1 or manifest.get('profile') != 'driving-v1'
                or manifest.get('source_sha256') != sha256(probe)):
            raise RouteWeftError('RouteWeft contract probe failed')
        if build_report(built, sha256(probe), 'reject', manifest=manifest) != report:
            raise RouteWeftError('contract probe preflight/build mismatch')
        external_output = Path(directory) / 'external-dataset'
        external = process.call('build', ['--input', str(probe.resolve()), '--profile', 'driving',
            '--invalid-restrictions', 'reject', '--builder', 'external', '--format', '2',
            '--graph-capacity', 'regional', '--output', str(external_output)], 60)
        external_verified = process.call('verify', ['--dataset', str(external_output),
            '--graph-capacity', 'regional', '--json'], 30)
        external_manifest = external_verified.get('manifest', {})
        if (external_verified.get('verified') is not True
                or external.get('manifest') != external_manifest
                or external_manifest.get('format') != 2
                or external_manifest.get('profile') != 'driving-v1'
                or external.get('build', {}).get('builder') != 'external'):
            raise RouteWeftError('RouteWeft external/v2 contract probe failed')
        build_report(external, sha256(probe), 'reject', manifest=external_manifest)
        return {'schema': 1, 'tool': {**process.identity,
                'binary': str(process.binary.resolve()), 'version': version['version'],
                'embedded_build': version.get('build'),
                'identity_verification': ('embedded-and-external' if version.get('build')
                                          else 'external-only'),
                'selection': ('locked-receipt' if process.identity.get('commit') else 'explicit-sha256')},
                'capabilities': version,
                'preflight': preflight, 'build': built, 'probe': verified,
                'external_build': external, 'external_probe': external_verified}
