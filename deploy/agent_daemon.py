#!/usr/bin/env python3
"""One native Codex app-server per saved hosted agent; no model turn on boot."""
import json
import os
from pathlib import Path
import sys
import tomllib

root = Path('/var/lib/dots-ops')
registry = json.loads((root / 'agents.json').read_text())
slug = sys.argv[1] if len(sys.argv) == 2 else ''
entry = next((v for v in registry.values() if v['profile'] == slug), None)
if entry is None:
    raise SystemExit('Unknown registered agent')
profile = tomllib.loads((root / '.codex' / (slug + '.config.toml')).read_text())
args = ['/opt/dots-codex/node_modules/.bin/codex']
for key in ('default_permissions', 'approval_policy', 'approvals_reviewer', 'developer_instructions'):
    args += ['-c', key + '=' + json.dumps(profile[key])]
args += ['app-server', '--listen', 'unix:///run/dots-agent-' + slug + '/control.sock']
os.chdir(entry['workspace'])
os.execv(args[0], args)
