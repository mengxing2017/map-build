"""Explicit, offline local source setup; regular builds never fetch tools."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
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


def setup(root: Path, workdir: Path, source: Path | None):
    lock = json.loads((root / 'config/routeweft.lock.json').read_text())
    if source is None:
        cache = workdir.resolve() / 'tools/routeweft/sources'
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
    target = workdir.resolve() / 'tools/routeweft' / lock['commit']
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rustup', 'run', channel, *lock['build'],
                    '--target-dir', str(target / 'target')], cwd=source, check=True)
    binary = target / 'routeweft'
    temporary = target / 'routeweft.new'
    shutil.copyfile(target / 'target/release/routeweft', temporary)
    temporary.chmod(0o755)
    doctor(RouteWeftProcess(temporary, sha256(temporary), commit=lock['commit']))
    os.replace(temporary, binary)
    receipt = {'schema': 1, 'commit': lock['commit'], 'binary_sha256': sha256(binary),
               'platform': platform.platform(), 'cargo_lock_sha256': sha256(source / 'backend/Cargo.lock'),
               'toolchain': subprocess.check_output(['rustup', 'run', channel, 'rustc', '--version'],
                                                  cwd=source, text=True).strip(),
               'built_at': datetime.now(timezone.utc).isoformat()}
    receipt_tmp = target / 'receipt.json.new'
    receipt_tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    os.replace(receipt_tmp, target / 'receipt.json')
    return receipt


def tool(root: Path, workdir: Path):
    lock = json.loads((root / 'config/routeweft.lock.json').read_text())
    target = workdir.resolve() / 'tools/routeweft' / lock['commit']
    binary = Path(os.environ.get('ROUTEWEFT_BIN', str(target / 'routeweft')))
    expected = os.environ.get('ROUTEWEFT_SHA256')
    receipt_path = Path(os.environ.get('ROUTEWEFT_RECEIPT', str(target / 'receipt.json')))
    if expected:
        return RouteWeftProcess(binary, expected)
    if not receipt_path.is_file():
        raise RouteWeftError(
            f'RouteWeft installation receipt not found: {receipt_path}. '
            f'Run make setup-routeweft WORKDIR="{workdir.resolve()}" '
            '(use the same actual WORKDIR as build/release), then retry. '
            'For an explicitly supplied ROUTEWEFT_BIN, provide its trusted '
            'ROUTEWEFT_SHA256 or ROUTEWEFT_RECEIPT.')
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('schema') != 1 or receipt.get('commit') != lock['commit']:
        raise RouteWeftError('receipt does not match tool lock')
    for key in ('platform', 'toolchain', 'cargo_lock_sha256', 'built_at'):
        if not receipt.get(key):
            raise RouteWeftError(f'missing receipt {key}')
    return RouteWeftProcess(binary, receipt['binary_sha256'], commit=lock['commit'])


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
        return {'schema': 1, 'tool': process.identity, 'capabilities': version,
                'preflight': preflight, 'build': built, 'probe': verified}
