from dataclasses import dataclass
import hashlib, json, pathlib, re

_TOKENS = re.compile(r'@[A-Za-z0-9_]+@|~|\*|<(?:PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG|VAR)>')

def normalize_source(source: str) -> str:
    return source.replace('\r\n', '\n').replace('\r', '\n')

def source_sha256(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode('utf-8')).hexdigest()

@dataclass(frozen=True)
class CatalogEntry:
    kind: str; key: str; source: str; source_sha256: str; context: str; origin: str; protected_tokens: tuple[str, ...]

    @classmethod
    def from_source(cls, kind, key, source, context, origin):
        return cls(kind, key, source, source_sha256(source), context, origin, tuple(_TOKENS.findall(source)))

    def as_dict(self):
        return {'context': self.context, 'key': self.key, 'kind': self.kind, 'origin': self.origin,
                'protected_tokens': list(self.protected_tokens), 'source': self.source, 'source_sha256': self.source_sha256}

def _merge(entries):
    out = {}
    for e in entries:
        old = out.get((e.kind, e.key))
        if old and old.source_sha256 != e.source_sha256: raise ValueError('duplicate key with different source hash: '+e.key)
        if old:
            origins = tuple(sorted(set(old.origin.split(';') + e.origin.split(';'))))
            out[(e.kind,e.key)] = CatalogEntry(e.kind,e.key,e.source,e.source_sha256,e.context,
                                               ';'.join(origins),e.protected_tokens)
        else: out[(e.kind,e.key)] = e
    return [out[k] for k in sorted(out)]

def load_catalog(path: pathlib.Path):
    return _merge(CatalogEntry(d['kind'],d['key'],d['source'],d['source_sha256'],d['context'],d['origin'],tuple(d.get('protected_tokens',())))
                   for line in path.read_text(encoding='utf-8').splitlines() if line.strip() for d in [json.loads(line)])

def write_catalog(path: pathlib.Path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(e.as_dict(), ensure_ascii=False, separators=(',', ':'))+'\n' for e in _merge(entries)), encoding='utf-8')

def parse_runtime_catalog(path):
    from .runtime_table import unescape_field
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        fields=line.split('\\t', 3) if '\\t' in line and '\t' not in line else line.split('\t', 3)
        if len(fields)!=4: raise ValueError('invalid runtime row')
        kind,key,digest,source=map(unescape_field, fields)
        rows.append(CatalogEntry(kind,key,source,digest,'gameplay','runtime-capture',tuple(_TOKENS.findall(source))))
    return rows
