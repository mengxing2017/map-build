#!/usr/bin/env python3
"""Stream command output unchanged and emit periodic Native setup stage progress."""
import math
import os
import signal
import subprocess
import sys
import threading
import time


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def main():
    if len(sys.argv) < 3:
        print('usage: native-progress.py STAGE COMMAND [ARG ...]', file=sys.stderr)
        return 2
    try:
        interval = float(os.environ.get('NATIVE_PROGRESS_INTERVAL_SECONDS', '10'))
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError()
    except ValueError:
        print('NATIVE_PROGRESS_INTERVAL_SECONDS must be a finite positive number', file=sys.stderr)
        return 2
    stage = sys.argv[1]
    started = time.monotonic()
    stopped = threading.Event()
    process = None
    monitor = None
    code = 1

    def log(status):
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        pid = process.pid if process is not None else '-'
        print(f'Native [{timestamp}] stage={stage} status={status} '
              f'pid={pid} elapsed={time.monotonic() - started:.1f}s',
              file=sys.stderr, flush=True)

    def heartbeat():
        while not stopped.wait(interval):
            log('RUNNING')

    def interrupted(signum, _frame):
        raise Interrupted(signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        process = subprocess.Popen(sys.argv[2:], start_new_session=True)
        log('START')
        monitor = threading.Thread(target=heartbeat, daemon=True)
        monitor.start()
        code = process.wait()
        if code < 0:
            code = 128 - code
    except Interrupted as error:
        code = 128 + error.signum
        if process is not None:
            try:
                os.killpg(process.pid, error.signum)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    except OSError as error:
        print(f'Native stage {stage}: {error}', file=sys.stderr, flush=True)
        code = 127
    finally:
        stopped.set()
        if monitor is not None and monitor.ident is not None:
            monitor.join()
        log('DONE' if code == 0 else f'FAILED(exit={code})')
    return code


if __name__ == '__main__':
    sys.exit(main())
