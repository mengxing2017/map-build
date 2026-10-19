"""Locked Git acquisition exercised against local repositories, without internet."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeSourceTests(unittest.TestCase):
    def test_fetches_exact_commit_reuses_cache_and_rejects_local_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin, cache = root/'origin', root/'cache'
            subprocess.run(['git','init','-q',str(origin)],check=True)
            def git(*args):
                return subprocess.check_output(['git','-C',str(origin),*args],text=True).strip()
            git('config','user.email','test@example.invalid')
            git('config','user.name','Native test')
            (origin/'source').write_text('locked')
            git('add','source'); git('commit','-qm','locked')
            revision=git('rev-parse','HEAD')
            (origin/'source').write_text('newer')
            git('commit','-qam','newer')
            command=['bash','-c','source "$1"; native_checkout_locked "$2" "$3" "$4"',
                     'test',str(ROOT/'scripts/lib/native-source.sh'),str(origin),revision,str(cache)]
            first=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(0,first.returncode,first.stderr)
            self.assertEqual('locked',(cache/'source').read_text())
            # An unavailable remote must not matter once the locked commit is cached.
            command[-3]=str(root/'missing-remote')
            subprocess.run(command,check=True,capture_output=True)
            (cache/'source').write_text('local edits')
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('unrecorded changes',result.stderr)
            self.assertEqual('local edits',(cache/'source').read_text())

    def test_unavailable_source_fails_without_publishing_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            result=subprocess.run(['bash','-c',
                'source "$1"; native_checkout_locked "$2" "$3" "$4"',
                'test',str(ROOT/'scripts/lib/native-source.sh'),str(root/'missing'),
                'a'*40,str(root/'cache')],capture_output=True,text=True,
                env={**os.environ,'NATIVE_FETCH_TIMEOUT_SECONDS':'5'})
            self.assertNotEqual(0,result.returncode)
            self.assertIn('Native source fetch failed', result.stderr)
            self.assertIn('cached sources are retained', result.stderr)
            self.assertFalse((root/'cache/source').exists())
