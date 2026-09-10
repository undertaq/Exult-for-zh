import pathlib, re, subprocess
from .catalog import CatalogEntry, parse_runtime_catalog, _merge

def make_dialogue_key(function, callsite, ordinal): return f'dialogue:0x{function:04x}:{callsite}:{ordinal}'
def make_choice_key(function, callsite, ordinal): return f'choice:0x{function:04x}:0x{callsite:04x}:{ordinal}'
def make_item_key(shape, frame, quality): return f'item:0x{shape:04x}:{frame}:{quality}'
def split_runtime_segments(s): return [x.lstrip('*') for x in s.split('~') if x]

def _static(root, ucxt):
    command=[str(ucxt),'-ftt',str(root)]
    if not (ucxt.stat().st_mode & 0o111): command=['/bin/sh']+command
    try:
        text=subprocess.check_output(command,text=True)
    except PermissionError:
        text=subprocess.check_output(['/bin/sh']+command,text=True)
    result=[]; fn=call=None; ordinal=0
    for line in text.splitlines():
        m=re.search(r'<(0x[0-9a-fA-F]+)>',line)
        if m:
            if fn is None: fn=int(m.group(1),16)
            elif call is None: call=m.group(1)
            continue
        m=re.search(r'`([^`]*)`',line)
        if m and fn is not None and call is not None:
            for part in split_runtime_segments(m.group(1)):
                result.append(CatalogEntry.from_source('dialogue',make_dialogue_key(fn,call,ordinal),part,'gameplay','static-ucxt')); ordinal+=1
    for p in root.rglob('*.uc'):
        for line in p.read_text(errors='ignore').splitlines():
            m=re.search(r'\["([^"\n]+)"(?:,\s*"([^"]+)")*\]',line)
            if m:
                for i,s in enumerate(re.findall(r'"([^"]+)"',m.group(0))): result.append(CatalogEntry.from_source('choice',f'choice:0x{fn or 0:04x}:unbound:{i}',s,'gameplay','static-usecode'))
    return result

def extract_catalog(mod_root, ucxt_path, runtime_catalog):
    entries=_static(mod_root,ucxt_path)
    msg=mod_root/'Ultima6v1.3'/'patch'/'textmsg.txt'
    if msg.exists():
        section=''
        for line in msg.read_text(encoding='utf-8').splitlines():
            if line.startswith('%%section '): section=line.split(None,1)[1]
            elif line.startswith('%%endsection'): section=''
            else:
                m=re.match(r'(0x[0-9a-fA-F]+):(.*)',line)
                if m and section: entries.append(CatalogEntry.from_source('textmsg','textmsg:'+m.group(1).lower(),m.group(2),'location' if section=='locations' else 'gameplay','static-textmsg'))
    if runtime_catalog:
        runtime = parse_runtime_catalog(runtime_catalog)
        bound_hashes = {e.source_sha256 for e in runtime if e.kind == 'choice'}
        static_choices = [e for e in entries if e.kind == 'choice' and ':unbound:' in e.key]
        for row in runtime:
            if row.kind == 'choice':
                for e in static_choices:
                    if e.source_sha256 == row.source_sha256:
                        entries.append(CatalogEntry(e.kind, row.key, e.source, e.source_sha256, e.context, e.origin, e.protected_tokens))
                        break
        entries = [e for e in entries if not (e.kind == 'choice' and ':unbound:' in e.key and e.source_sha256 in bound_hashes)]
        entries.extend(runtime)
    return _merge(entries)
