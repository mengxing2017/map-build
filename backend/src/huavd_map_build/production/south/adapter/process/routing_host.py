"""Linux host/cgroup and filesystem observations, with no region knowledge."""
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
import time


def unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


@dataclass(frozen=True)
class HostResources:
    available_bytes: int | None
    cgroup_remaining_bytes: tuple[int, ...]
    detection_complete: bool
    evidence: tuple[dict, ...]
    observed_at: float

    def as_dict(self):
        return asdict(self)


def observe(proc=Path('/proc'), filesystem=Path('/')):
    evidence, remaining = [], []
    available = None
    complete = True
    try:
        meminfo = (proc / 'meminfo').read_text()
        match = re.search(r'^MemAvailable:\s+(\d+) kB$', meminfo, re.M)
        available = int(match[1]) * 1024 if match else None
        if available is None:
            complete = False
        groups = [line.split(':', 2) for line in (proc / 'self/cgroup').read_text().splitlines()]
        mounts = []
        for line in (proc / 'self/mountinfo').read_text().splitlines():
            before, after = line.split(' - ', 1)
            fields, fs = before.split(), after.split()
            if fs[0] in ('cgroup', 'cgroup2'):
                mounts.append((PurePosixPath(unescape(fields[3])), PurePosixPath(unescape(fields[4])), fs))
        memory_groups = [(controllers, PurePosixPath(unescape(path))) for _, controllers, path in groups
                         if controllers == '' or 'memory' in controllers.split(',')]
        for controllers, group in memory_groups:
            matched = False
            for mount_root, mount_point, fs in mounts:
                if (controllers == '' and fs[0] != 'cgroup2') or (controllers != '' and
                        (fs[0] != 'cgroup' or 'memory' not in fs[2].split(','))):
                    continue
                if not group.is_relative_to(mount_root):
                    continue
                matched = True
                base = filesystem / str(mount_point).lstrip('/')
                current = base / str(group.relative_to(mount_root))
                # A non-root mounted subtree can hide an ancestor constraint.
                if str(mount_root) != '/':
                    complete = False
                    evidence.append({'hidden_ancestors': str(mount_root)})
                while True:
                    limit_name, usage_name = (('memory.max', 'memory.current') if controllers == '' else
                                              ('memory.limit_in_bytes', 'memory.usage_in_bytes'))
                    limit_path = current / limit_name
                    usage_path = current / usage_name
                    # A cgroup v2 root has no memory.max; MemAvailable constrains it.
                    if current == base and not limit_path.exists() and mount_root == PurePosixPath('/'):
                        break
                    try:
                        limit_text = limit_path.read_text().strip()
                        usage = int(usage_path.read_text().strip())
                        limit = None if limit_text == 'max' else int(limit_text)
                        if usage < 0 or (limit is not None and limit < 0):
                            raise ValueError('negative cgroup memory counter')
                        if limit is not None and limit < (1 << 60):
                            remaining.append(max(0, limit - usage))
                        evidence.append({'path': str(current), 'limit': limit, 'usage': usage})
                    except (OSError, ValueError) as error:
                        complete = False
                        evidence.append({'path': str(current), 'error': str(error)})
                    if current == base:
                        break
                    current = current.parent
            if not matched:
                complete = False
                evidence.append({'unmapped_cgroup': str(group)})
        if not memory_groups:
            complete = False
    except (OSError, ValueError, IndexError) as error:
        complete = False
        evidence.append({'error': str(error)})
    return HostResources(available, tuple(remaining), complete, tuple(evidence), time.time())


def filesystem_info(path, mounts=Path('/proc/self/mountinfo')):
    path = Path(path).resolve()
    chosen, kind = -1, None
    try:
        for line in mounts.read_text().splitlines():
            before, after = line.split(' - ', 1)
            mount = Path(unescape(before.split()[4]))
            if path.is_relative_to(mount) and len(str(mount)) >= chosen:
                chosen, kind = len(str(mount)), after.split()[0]
    except (OSError, ValueError, IndexError):
        pass
    return {'path': str(path), 'free_bytes': shutil.disk_usage(path).free, 'filesystem': kind}
