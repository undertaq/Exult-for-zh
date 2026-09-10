from dataclasses import dataclass
import pathlib

@dataclass(frozen=True)
class RuntimeRow:
    kind: str; key: str; source_sha256: str; zh: str

def escape_field(s): return s.replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r','\\r')
def unescape_field(s):
    out=[]; i=0
    while i<len(s):
        if s[i]!='\\': out.append(s[i]); i+=1; continue
        i+=1
        if i==len(s): raise ValueError('trailing escape')
        c=s[i]; i+=1
        if c not in 'tnr\\': raise ValueError('unknown escape')
        out.append({'t':'\t','n':'\n','r':'\r','\\':'\\'}[c])
    return ''.join(out)
def load_runtime_table(path):
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        f=line.split('\\t',3) if '\\t' in line and '\t' not in line else line.split('\t',3)
        if len(f)!=4: raise ValueError('invalid runtime table row')
        rows.append(RuntimeRow(*(unescape_field(x) for x in f)))
    return rows
def write_runtime_table(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join('\t'.join(escape_field(x) for x in (r.kind,r.key,r.source_sha256,r.zh))+'\n' for r in rows),encoding='utf-8')
