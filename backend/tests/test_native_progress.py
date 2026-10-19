"""Real subprocess checks for Native setup heartbeat and exit/signal semantics."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/lib/native-progress.py'


class NativeProgressTests(unittest.TestCase):
    def command(self, program):
        return [sys.executable, str(SCRIPT), 'test-stage', sys.executable, '-c', program]

    def test_silent_command_has_periodic_progress_and_preserves_output(self):
        result = subprocess.run(self.command(
            'import time,sys; time.sleep(.25); print("payload"); print("diagnostic",file=sys.stderr)'),
            capture_output=True, text=True,
            env={**os.environ, 'NATIVE_PROGRESS_INTERVAL_SECONDS': '0.05'})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('payload\n', result.stdout)
        self.assertIn('diagnostic', result.stderr)
        self.assertGreaterEqual(result.stderr.count('status=RUNNING'), 2)
        self.assertIn('stage=test-stage status=START pid=', result.stderr)
        self.assertIn('status=DONE', result.stderr)
        self.assertIn('elapsed=', result.stderr)

    def test_command_failure_is_not_hidden(self):
        result = subprocess.run(self.command('raise SystemExit(7)'),capture_output=True,text=True)
        self.assertEqual(7, result.returncode)
        self.assertIn('status=FAILED(exit=7)', result.stderr)
        self.assertNotIn('status=DONE', result.stderr)

    def test_invalid_interval_does_not_start_command(self):
        for value in ('0', '-1', 'nan', 'inf', 'invalid'):
            with self.subTest(value=value):
                result = subprocess.run(self.command('print("must not execute")'),
                    capture_output=True,text=True,
                    env={**os.environ,'NATIVE_PROGRESS_INTERVAL_SECONDS':value})
                self.assertEqual(2,result.returncode)
                self.assertEqual('',result.stdout)

    def test_sigterm_stops_child_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary)/'orphan'
            descendant = f'import time,pathlib; time.sleep(.5); pathlib.Path({str(marker)!r}).touch()'
            program = (f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{descendant!r}]); '
                       'print("child-ready",flush=True); time.sleep(10)')
            process = subprocess.Popen(self.command(program),stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,text=True)
            self.addCleanup(lambda: process.kill() if process.poll() is None else None)
            self.assertIn('status=START',process.stderr.readline())
            self.assertEqual('child-ready\n',process.stdout.readline())
            process.send_signal(signal.SIGTERM)
            _,error=process.communicate(timeout=10)
            self.assertEqual(143,process.returncode,error)
            time.sleep(.6)
            self.assertFalse(marker.exists())
            self.assertIn('status=FAILED(exit=143)',error)
