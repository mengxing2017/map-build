"""Setup wiring and pinned Rust selection, without network downloads."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process.routeweft_tools import ensure_rust_toolchain, setup, tool
from huavd_map_build.production.south.adapter.process.routeweft import sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError

ROOT = Path(__file__).resolve().parents[2]


class RouteWeftSetupTests(unittest.TestCase):
    def test_new_map_workspace_reuses_shared_installation(self):
        binary, _, receipt = self.cached_installation()
        maps = self.root / 'new-map-workspace'
        with patch.dict(os.environ, {'HUAVD_TOOLS_DIR': str(self.root / 'tools')}, clear=True), \
                patch('huavd_map_build.production.south.adapter.process.routeweft_tools.doctor'), \
                patch('subprocess.run') as run:
            self.assertEqual(binary, tool(ROOT, maps).binary)
            self.assertEqual(receipt, setup(ROOT, maps, None))
            run.assert_not_called()
            self.assertFalse(maps.exists())

    def test_map_workspace_installation_is_ignored(self):
        _, _, receipt = self.cached_installation()
        maps = self.root / 'maps'
        local = maps / 'tools/routeweft' / receipt['commit']
        local.mkdir(parents=True)
        (local / 'receipt.json').write_text(json.dumps(receipt))
        with patch.dict(os.environ, {'HUAVD_TOOLS_DIR': str(self.root / 'tools')}, clear=True):
            self.assertEqual(self.root / 'tools/routeweft' / receipt['commit'] / 'routeweft', tool(ROOT, maps).binary)


    def cached_installation(self):
        os.environ['HUAVD_TOOLS_DIR'] = str(self.root / 'tools')
        lock = json.loads((ROOT / 'config/routeweft.lock.json').read_text())
        target = self.root / 'tools/routeweft' / lock['commit']
        target.mkdir(parents=True)
        binary = target / 'routeweft'
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        receipt = dict(schema=1, commit=lock['commit'], binary_sha256=sha256(binary),
                       platform='test', toolchain='test', cargo_lock_sha256='a'*64, built_at='test')
        path = target / 'receipt.json'
        path.write_text(json.dumps(receipt))
        return binary, path, receipt

    def test_repeated_setup_reuses_verified_cache_without_git_or_rustup(self):
        _, _, receipt = self.cached_installation()
        with patch('huavd_map_build.production.south.adapter.process.routeweft_tools.doctor') as doctor, \
                patch('subprocess.run') as run, patch('subprocess.check_output') as output, \
                patch.dict(os.environ, {'ROUTEWEFT_BIN': '/invalid/override'}):
            for _ in range(2):
                self.assertEqual(receipt, setup(ROOT, self.root, None))
            self.assertEqual(2, doctor.call_count)
            run.assert_not_called()
            output.assert_not_called()

    def test_invalid_cache_rebuilds_instead_of_reusing(self):
        for invalid in ('digest', 'commit', 'probe'):
            with self.subTest(invalid=invalid):
                if invalid != 'digest':
                    # Each case uses an independent work directory.
                    self.root = self.root / invalid
                binary, path, receipt = self.cached_installation()
                if invalid == 'digest':
                    binary.write_text('corrupt')
                elif invalid == 'commit':
                    receipt['commit'] = 'wrong'
                    path.write_text(json.dumps(receipt))
                with patch('huavd_map_build.production.south.adapter.process.routeweft_tools.doctor',
                           side_effect=RouteWeftError('failed probe')), \
                        patch('subprocess.run', side_effect=RuntimeError('rebuild started')) as run:
                    with self.assertRaisesRegex(RuntimeError, 'rebuild started'):
                        setup(ROOT, self.root, None)
                    self.assertEqual('git', run.call_args.args[0][0])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(os.environ, {'HUAVD_TOOLS_DIR': str(self.root / 'tools')})
        environment.start()
        self.addCleanup(environment.stop)
        (self.root / 'rust-toolchain.toml').write_text(
            '[toolchain]\nchannel = "1.97.1"\nprofile = "minimal"\n')

    @patch('shutil.which', return_value='/bin/rustup')
    def test_installs_required_version_even_with_another_toolchain(self, _which):
        with patch('subprocess.check_output', return_value='stable-x86_64-unknown-linux-gnu (default)\n'), \
                patch('subprocess.run') as run:
            self.assertEqual('1.97.1', ensure_rust_toolchain(self.root))
            run.assert_called_once_with(
                ['rustup', 'toolchain', 'install', '1.97.1', '--profile', 'minimal'], check=True)

    @patch('shutil.which', return_value='/bin/rustup')
    def test_installed_required_version_does_not_download(self, _which):
        with patch('subprocess.check_output', return_value='1.97.1-x86_64-unknown-linux-gnu\n'), \
                patch('subprocess.run') as run:
            self.assertEqual('1.97.1', ensure_rust_toolchain(self.root))
            run.assert_not_called()

    @patch('shutil.which', return_value='/bin/rustup')
    def test_toolchain_installation_failure_is_not_ignored(self, _which):
        with patch('subprocess.check_output', return_value=''), \
                patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'rustup')):
            with self.assertRaises(subprocess.CalledProcessError):
                ensure_rust_toolchain(self.root)

    @patch('shutil.which', return_value=None)
    def test_missing_rustup_explains_devbox_environment(self, _which):
        with self.assertRaisesRegex(RouteWeftError, 'devbox shell'):
            ensure_rust_toolchain(self.root)

    def test_unconfigured_cargo_shim_triggers_toolchain_installation(self):
        command = ['bash', '-c',
                   'source "$1"; cargo() { return 1; }; '
                   'rustup() { printf "%s\\n" "$*"; }; ensure_cargo_toolchain',
                   'setup-test', str(ROOT / 'scripts/setup-tools.sh')]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('default stable', result.stdout)

    def test_unified_setup_passes_actual_workdir_source_and_propagates_failure(self):
        wrapper = self.root / 'python stub'
        record = self.root / 'arguments'
        wrapper.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$SETUP_TEST_RECORD"\nexit "${SETUP_TEST_EXIT:-0}"\n')
        wrapper.chmod(0o755)
        environment = {**os.environ, 'HUAVD_MAP_BUILD_PYTHON': str(wrapper),
                       'WORKDIR': str(self.root / 'map work'), 'SETUP_TEST_RECORD': str(record),
                       'ROUTEWEFT_SOURCE': str(self.root / 'local source')}
        command = ['bash', '-c', 'source "$1"; install_routeweft', 'setup-test',
                   str(ROOT / 'scripts/setup-tools.sh')]
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        arguments = record.read_text().splitlines()
        self.assertEqual(['-m', 'huavd_map_build', 'routing', 'setup',
                          f'--workdir={environment["WORKDIR"]}',
                          f'--source={environment["ROUTEWEFT_SOURCE"]}'], arguments)
        environment['SETUP_TEST_EXIT'] = '9'
        self.assertNotEqual(0, subprocess.run(command, env=environment,
                                            capture_output=True).returncode)
