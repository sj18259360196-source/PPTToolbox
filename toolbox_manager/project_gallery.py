"""Bounded, cached project preview index. Never starts Office or alters projects."""
import io, os, re, time, stat, json, hashlib
from pathlib import Path
from .workbench import Workbench


def gallery(manager, key):
    wb = Workbench(manager); root, _, state = wb.entry(key)
    cache = getattr(manager, '_gallery_cache', {})
    cached = cache.get(key)
    identity = (str(root), state.get('revision'))
    if cached and cached[0] == identity and time.monotonic() - cached[1] < 15: return cached[2]
    groups = {}; names = []; count = 0; limited = False
    for top in ('delivery', 'runs', 'input'):
        base = wb.path(root, top)
        if not base.is_dir(): continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not (getattr((Path(directory)/d).lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))
            for name in sorted(files):
                count += 1
                if count > 5000: limited = True; break
                p = Path(directory)/name
                try: p = wb.path(root, p.relative_to(root))
                except (ValueError, OSError): continue
                rel = p.relative_to(root).as_posix()
                if p.suffix.lower() == '.pptx': names.append(rel)
                if p.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}: continue
                parts = p.relative_to(root).parts
                reference = top == 'input'
                if not reference and (not re.fullmatch(r'slide[-_]?\d+\.(png|jpe?g|webp)', name, re.I)
                    or not re.match(r'(office|render|preview)', p.parent.name, re.I)): continue
                version = '参考图' if reference else parts[1]
                group_key = (top, version)
                row = groups.setdefault(group_key, {'version': version, 'kind': {'delivery':'成品','runs':'候选','input':'参考图'}[top], 'pages':[], 'pptx':None})
                row['pages'].append({'path':rel,'name':name,'modified_ns':p.stat().st_mtime_ns})
            if limited: break
        if limited: break
    result = []
    for (top, version), row in groups.items():
        pages = row['pages']
        # Each render folder is a full export; choose one, never combine duplicate pages.
        newest = max(pages, key=lambda p:p['modified_ns'])['path'].rsplit('/',1)[0]
        row['pages'] = sorted((p for p in pages if p['path'].rsplit('/',1)[0] == newest), key=lambda p:p['name'])
        prefix = f'{top}/{version}/'
        candidates = [n for n in names if n.startswith(prefix)]
        row['pptx'] = next((n for n in candidates if n == prefix+'editable.pptx'), None)
        if top != 'input':
            try:
                receipt = json.loads(wb.path(root, newest+'/office-render.json').read_text(encoding='utf-8-sig'))
                expected = receipt.get('pptx_sha256')
                if expected:
                    row['pptx'] = next((n for n in candidates if hashlib.sha256(wb.path(root,n).read_bytes()).hexdigest()==expected),None)
            except (OSError,ValueError): pass
        result.append(row)
    result.sort(key=lambda r:({'成品':0,'候选':1,'参考图':2}[r['kind']], -max(p['modified_ns'] for p in r['pages'])))
    value = {'versions':result, 'search_text':' '.join(names), 'limited':limited}
    cache[key] = (identity, time.monotonic(), value); manager._gallery_cache = cache
    return value


def image(manager, key, relative, full=False):
    wb = Workbench(manager); root, _, _ = wb.entry(key)
    index = gallery(manager, key)
    if not any(p['path'] == relative for r in index['versions'] for p in r['pages']): raise ValueError('预览不属于此项目')
    p = wb.path(root, relative)
    from PIL import Image, ImageOps
    with Image.open(p) as source:
        im = ImageOps.exif_transpose(source).convert('RGB')
        im.thumbnail((1920,1920) if full else (420,280))
        out = io.BytesIO(); im.save(out,format='JPEG',quality=88)
        return out.getvalue()
