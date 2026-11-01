#!/usr/bin/env python3
"""One checkpoint write, projected through the existing crew WebSocket connector."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

SCHEMA = 'vmfactory.crew-work/1'
FIELDS = {'focus': 480, 'checkpoint': 160, 'artifact': 500, 'next': 480, 'blocker': 480, 'commit': 64}
PHASES = {'working', 'checkpoint', 'blocked', 'complete', 'waiting', 'stopped'}
DEFAULT = Path('/workspace/FMVisual/telemetry')


def report_path(root, agent):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', agent):
        raise ValueError('Invalid agent ID')
    return Path(root) / (agent + '.json')


def read_report(root, agent):
    path = report_path(root, agent)
    try:
        if path.is_symlink() or path.stat().st_size > 8192:
            return None
        value = json.loads(path.read_text())
        if value.get('schema') != SCHEMA or value.get('agent') != agent or value.get('phase') not in PHASES:
            return None
        at = value.get('reportedAt')
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 < at <= time.time() + 30:
            return None
        return {'schema': SCHEMA, 'agent': agent, 'phase': value['phase'], 'reportedAt': at,
                **{key: str(value.get(key, ''))[:limit] for key, limit in FIELDS.items()}}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def write_report(root, agent, phase, values):
    if phase not in PHASES:
        raise ValueError('Unknown report phase')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = report_path(root, agent)
    value = {'schema': SCHEMA, 'agent': agent, 'phase': phase, 'reportedAt': time.time(),
             **{key: str(values.get(key, ''))[:limit] for key, limit in FIELDS.items()}}
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.crew-work-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('agent')
    parser.add_argument('--root', type=Path, default=DEFAULT)
    parser.add_argument('--phase', choices=sorted(PHASES), default='checkpoint')
    for key in FIELDS:
        parser.add_argument('--' + key, default='')
    args = parser.parse_args()
    values = vars(args)
    if not args.commit:
        result = subprocess.run(['git', '-C', '/workspace/FMVisual/project', 'rev-parse', 'HEAD'], capture_output=True, text=True)
        values['commit'] = result.stdout.strip() if result.returncode == 0 else ''
    write_report(args.root, args.agent, args.phase, values)
    print(report_path(args.root, args.agent))


if __name__ == '__main__':
    main()
