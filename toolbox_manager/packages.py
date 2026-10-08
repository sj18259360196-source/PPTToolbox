"""Offline package inspection. Import never executes package code or installs dependencies."""
from __future__ import annotations
import io,json,re,stat,unicodedata,zipfile
from pathlib import Path,PurePosixPath
from .storage import digest
from . import VERSION, API_VERSION

LIMIT=128*1024*1024
RESERVED={'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}


def compatibility(manifest):
    requirements=manifest.get('compatibility') if isinstance(manifest,dict) else None
    if requirements is None:
        return {'status':'undeclared','message':'未声明兼容范围，请核对扩展说明'}
    fields={'manager_api','min_product_version','max_product_version_exclusive'}
    if not isinstance(requirements,dict) or not requirements or set(requirements)-fields:
        raise ValueError('无效的扩展兼容声明')
    def number(value):
        if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):
            raise ValueError('软件兼容范围需要三段数字版本')
        return tuple(map(int,value.split('.')))
    lower=number(requirements['min_product_version']) if 'min_product_version' in requirements else None
    upper=number(requirements['max_product_version_exclusive']) if 'max_product_version_exclusive' in requirements else None
    if lower and upper and lower>=upper:raise ValueError('软件兼容范围为空')
    api=requirements.get('manager_api')
    if 'manager_api' in requirements and (not isinstance(api,str) or not api or len(api)>100):
        raise ValueError('无效的接口协议声明')
    supported=(api is None or api==API_VERSION) and (lower is None or number(VERSION)>=lower) and (upper is None or number(VERSION)<upper)
    return {'status':'compatible' if supported else 'incompatible','requirements':requirements,
            'message':'符合声明的兼容范围' if supported else '此扩展与当前软件版本或接口协议不兼容'}


def installed_compatibility(path):
    manifest=Path(path)/'MANIFEST.json'
    try:
        return compatibility(json.loads(manifest.read_text(encoding='utf-8-sig')) if manifest.is_file() else {})
    except (OSError,ValueError):
        return {'status':'incompatible','message':'无法读取扩展兼容声明，请重新检查工具包'}


def safe_name(name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\x00' in name:raise ValueError('压缩包路径非法')
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or name.rstrip('/')!=p.as_posix():raise ValueError('压缩包路径越界或不规范')
    for part in p.parts:
        if part.endswith((' ','.')) or part.split('.')[0].casefold() in RESERVED:raise ValueError('不兼容的 Windows 文件名')
    return p


def metadata(files):
    if 'SKILL.md' in files:
        text=files['SKILL.md'].decode('utf-8-sig')
        if not text.startswith('---'):raise ValueError('SKILL.md 缺少 front matter')
        header=text.split('---',2)[1]
        def field(key,default=''):
            m=re.search(r'^\s*'+key+r':\s*[\"\']?([^\n\"\']+)',header,re.M)
            return m[1].strip() if m else default
        name=field('name');version=field('version','0.0.0');desc=field('description')
    elif '.codex-plugin/plugin.json' in files:
        m=json.loads(files['.codex-plugin/plugin.json']);name=m.get('name');version=m.get('version','0.0.0');desc=m.get('description','')
    else:raise ValueError('需要包含 SKILL.md 或 .codex-plugin/plugin.json 的完整工具包')
    if not isinstance(name,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',name):raise ValueError('无效的 Skill / 插件名称')
    if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise ValueError('版本需为语义版本号')
    if 'toolbox/registry.json' in files:
        r=json.loads(files['toolbox/registry.json']);ids=[t['id'] for t in r.get('tools',[])]
        if len(ids)!=len(set(ids)):raise ValueError('工具 ID 重复')
        for row in r.get('tools',[]):
            for entry in [row.get('entry'),*row.get('manuals',[])]:
                if entry:
                    safe_name(entry)
                    if entry not in files:raise ValueError('工具或手册文件缺失: '+entry)
    return {'name':name,'version':version,'description':desc}


def inspect_zip(data):
    if len(data)>32*1024*1024:raise ValueError('ZIP 不得超过 32 MB')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=z.infolist()
        if len(infos)>5000 or sum(x.file_size for x in infos)>LIMIT:raise ValueError('ZIP 解压体积或文件数超限')
        seen=set();raw={}
        for i in infos:
            p=safe_name(i.filename)
            key=unicodedata.normalize('NFC',p.as_posix()).casefold()
            if key in seen:raise ValueError('ZIP 内文件名重复或大小写冲突')
            seen.add(key)
            if stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:raise ValueError('拒绝符号链接或加密包')
            if i.file_size>24*1024*1024 or i.file_size>max(i.compress_size,1)*500:raise ValueError('单文件过大或压缩比异常')
            if i.is_dir():continue
            if p.suffix.lower() in {'.ttf','.otf','.ttc','.woff','.woff2','.pem','.key'}:raise ValueError('不接收字体或密钥文件')
            raw[p.as_posix()]=z.read(i)
    if 'SKILL.md' not in raw and '.codex-plugin/plugin.json' not in raw:
        roots={PurePosixPath(n).parts[0] for n in raw}
        if len(roots)!=1:raise ValueError('ZIP 只能有一个工具包根目录')
        prefix=next(iter(roots))+'/'
        raw={n[len(prefix):]:b for n,b in raw.items()}
    meta=metadata(raw)
    integrity='unmanifested';compatible=compatibility({})
    if 'MANIFEST.json' in raw:
        m=json.loads(raw['MANIFEST.json']);rows=m.get('files',[])
        compatible=compatibility(m)
        if not isinstance(rows,list):raise ValueError('无效的 MANIFEST')
        paths=[r.get('path') for r in rows]
        if len(paths)!=len(set(paths)) or set(paths)!=set(raw)-{'MANIFEST.json'}:raise ValueError('文件清单与 ZIP 不一致')
        for row in rows:
            safe_name(row['path']);b=raw[row['path']]
            if row.get('sha256')!=digest(b) or row.get('size')!=len(b):raise ValueError('文件校验失败: '+row['path'])
        integrity='manifest_verified'
    files_hash=digest(json.dumps({n:digest(b) for n,b in sorted(raw.items())},sort_keys=True))
    return {**meta,'compatibility':compatible,'files':raw,'fingerprint':files_hash,'integrity':integrity,'archive_sha256':digest(data),'file_count':len(raw)}


def tree_hashes(root, *, exclude_root=()):
    import os
    root=Path(root).resolve();out={}
    ignored={'__pycache__','.pytest_cache','.git','.venv','node_modules'}
    for folder,dirs,files in os.walk(root):
        current=Path(folder)
        dirs[:]=[name for name in dirs if name not in ignored and not (current==root and name in exclude_root)]
        if any((current/name).is_symlink() for name in dirs):raise ValueError('包目录包含符号链接')
        for name in files:
            p=current/name
            if p.is_symlink():raise ValueError('包目录包含符号链接')
            if p.is_file():out[p.relative_to(root).as_posix()]=digest(p.read_bytes())
    return out
