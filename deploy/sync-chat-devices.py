#!/usr/bin/env python3
"""Sync only phone credential hashes; provider logins never leave the Mac."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

base = Path.home() / '.local/share/dots'
hashes = list(json.loads((base / 'paired-phones.json').read_text()))
hashes.append(hashlib.sha256((base / 'mobile-token').read_text().strip().encode()).hexdigest())
remote = '''import sys,json,os,tempfile,grp
from pathlib import Path
values=json.load(sys.stdin)
if not isinstance(values,list) or not all(isinstance(x,str) and len(x)==64 and all(c in "0123456789abcdef" for c in x) for x in values):
 raise SystemExit("Invalid device hashes")
path=Path('/etc/dots-hub/device-hashes.json')
path.parent.mkdir(mode=0o750,exist_ok=True)
os.chown(path.parent,0,grp.getgrnam('dots-ops').gr_gid)
fd,temp=tempfile.mkstemp(dir=path.parent)
os.fchmod(fd,0o640);os.fchown(fd,0,grp.getgrnam('dots-ops').gr_gid)
with os.fdopen(fd,'w') as f: json.dump(sorted(set(values)),f)
os.replace(temp,path)
'''
subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@88.216.68.234',
                'python3 -c ' + shlex.quote(remote)], input=json.dumps(hashes), text=True, check=True)
