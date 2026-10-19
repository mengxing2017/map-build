"""Setup wiring and pinned Rust selection, without network downloads."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process.routeweft_tools import ensure_rust_toolchain
from huavd_map_build.production.south.port.routeweft import RouteWeftError

ROOT = Path(__file__).resolve().parents[2]


class RouteWeftSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
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
