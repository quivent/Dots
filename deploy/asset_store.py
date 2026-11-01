"""Immutable scene bytes, separate from the SQLite metadata and WebSocket stream."""
import hashlib,os,re,tempfile
from pathlib import Path
HASH=re.compile(r'^[0-9a-f]{64}$')
MAX_BLOB=64*1024*1024
class AssetStore:
 def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
 def path(self,digest):
  if not HASH.fullmatch(digest):raise ValueError('Invalid content identity')
  return self.root/digest
 async def receive(self,digest,chunks):
  target=self.path(digest);fd,name=tempfile.mkstemp(dir=self.root,prefix='.upload-');h=hashlib.sha256();size=0
  try:
   with os.fdopen(fd,'wb') as out:
    async for data in chunks:
     size+=len(data)
     if size>MAX_BLOB:raise ValueError('Asset exceeds bound')
     h.update(data);out.write(data)
    out.flush();os.fsync(out.fileno())
   if h.hexdigest()!=digest:raise ValueError('Content identity mismatch')
   os.replace(name,target)
   return size
  finally:
   if os.path.exists(name):os.unlink(name)
