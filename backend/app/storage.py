import os, json, hashlib
from pathlib import Path
from typing import Protocol

class Storage(Protocol):
    def path(self, key: str) -> Path: ...
class LocalStorage:
    def __init__(self):
        self.root = Path(os.getenv('STORAGE_ROOT', './data')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
    def path(self, key):
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root): raise ValueError('Invalid asset path')
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    def json(self, key, value=None):
        p = self.path(key)
        if value is None: return json.loads(p.read_text('utf-8')) if p.exists() else None
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False), 'utf-8'); tmp.replace(p)
store = LocalStorage()
def digest(*values): return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
