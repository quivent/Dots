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
remote = '''import sys,json,os,tempfile,grp,fcntl,time
from pathlib import Path
values=json.load(sys.stdin)
if not isinstance(values,list) or not all(isinstance(x,str) and len(x)==64 and all(c in "0123456789abcdef" for c in x) for x in values):
 raise SystemExit("Invalid device hashes")
path=Path('/etc/dots-hub/device-hashes.json')
path.parent.mkdir(mode=0o750,exist_ok=True)
os.chown(path.parent,0,grp.getgrnam('dots-ops').gr_gid)
with open(path.with_name('device-hashes.lock'),'a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 lease_path=path.with_name('local-owner-leases.json')
 ledger=json.loads(lease_path.read_text()) if lease_path.exists() else {'schema':'dots.local-owner-leases/1','leases':{}}
 if ledger.get('schema')!='dots.local-owner-leases/1' or not isinstance(ledger.get('leases'),dict):
  raise SystemExit('Invalid local owner lease ledger; preserving previous registry')
 now=time.time();active=[]
 for digest,expires in ledger['leases'].items():
  if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest) or type(expires) not in (float,int):
   raise SystemExit('Invalid local owner lease; preserving previous registry')
  if expires>now:active.append(digest)
 # The Mac set remains authoritative for permanent phones and revocations.
 # Only explicit unexpired local leases survive source replacement.
 fd,temp=tempfile.mkstemp(dir=path.parent)
 os.fchmod(fd,0o640);os.fchown(fd,0,grp.getgrnam('dots-ops').gr_gid)
 with os.fdopen(fd,'w') as f:
  json.dump(sorted(set(values)|set(active)),f);f.flush();os.fsync(f.fileno())
 os.replace(temp,path)

'''
subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@88.216.68.234',
                'python3 -c ' + shlex.quote(remote)], input=json.dumps(hashes), text=True, check=True)
