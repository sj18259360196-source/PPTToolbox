"""Owner-created material workspaces. Never initializes or executes a workflow."""
from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from PIL import Image

from .policy import plain_path
from .storage import digest, stamp

KEY = 'prepared_tasks'


def rows(manager):
    return manager.store.get(KEY, {})


def get(manager, key):
    row = rows(manager).get(key)
    if not row:
        raise ValueError('准备任务不存在，请刷新项目列表')
    return row


def mutate(manager, key, revision, fn):
    with manager.store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        entry = c.execute('SELECT value FROM kv WHERE key=?', (KEY,)).fetchone()
        items = json.loads(entry[0]) if entry else {}
        row = items.get(key)
        if not row or row['revision'] != revision:
            raise ValueError('准备任务已变更，请重新打开后继续')
        fn(row)
        row['revision'] += 1
        row['updated'] = stamp()
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (KEY, json.dumps(items, ensure_ascii=False)))
    return row


def create(manager, body):
    key = body.get('id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise ValueError('需要有效的新建请求编号')
    name = body.get('name', '').strip()
    if not 1 <= len(name) <= 100 or any(c in name for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in name):
        raise ValueError('项目名称不可包含路径符号，长度为 1 到 100 字')
    root = Path(manager._projects_directory(body.get('root', '')))
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('请选择已存在的项目根目录')
    with manager.store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        entry = c.execute('SELECT value FROM kv WHERE key=?', (KEY,)).fetchone()
        items = json.loads(entry[0]) if entry else {}
        if key in items:
            old = items[key]
            if old['name'] != name or plain_path(old['root']) != plain_path(root):
                raise ValueError('请求编号已用于另一项制作')
            return old
        workspace = plain_path(root / (name.rstrip('. ') + '-' + key[:8]))
        workspace.mkdir(exist_ok=False)
        (workspace / 'input').mkdir()
        row = {'id': key, 'name': name, 'root': str(root), 'workspace': str(workspace),
               'project': str(workspace / 'project'), 'inputs': [], 'requirements': '',
               'category': '研究汇报', 'archived': False, 'ready': False, 'revision': 0,
               'created': stamp(), 'updated': stamp()}
        items[key] = row
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (KEY, json.dumps(items, ensure_ascii=False)))
    manager.store.event('preparation.created', '新建制作材料工作区', source='owner', details={'id': key})
    return row


def input_file(row, item):
    root = plain_path(Path(row['workspace']) / 'input')
    path = plain_path(root / item['saved_name'])
    if path.parent != root or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('图片副本不存在或路径已改变')
    if digest(path.read_bytes()) != item['sha256']:
        raise ValueError('图片副本已在外部修改，请重新导入')
    return path


def upload(manager, body):
    name = body.get('name', '')
    if not isinstance(name, str) or not name or len(name) > 250:
        raise ValueError('图片文件名不合法')
    try:
        data = base64.b64decode(body['data'], validate=True)
    except (KeyError, ValueError) as e:
        raise ValueError('图片编码无效') from e
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError('每张图片不得超过 20 MB')
    with Image.open(io.BytesIO(data)) as im:
        fmt, width, height = im.format, *im.size
        if fmt not in {'PNG', 'JPEG', 'WEBP'} or width * height > 40_000_000:
            raise ValueError('仅支持 PNG、JPEG、WebP，最多 4000 万像素')
        im.verify()
    sha = digest(data)
    def add(row):
        if any(f['sha256'] == sha for f in row['inputs']):
            raise ValueError('重复图片，已保留现有副本')
        if len(row['inputs']) >= 30:
            raise ValueError('每项制作最多 30 张图片')
        folder = plain_path(Path(row['workspace']) / 'input')
        ext = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[fmt]
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(name).stem).strip('. ')[:75] or 'image'
        if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', stem):
            stem = '_' + stem
        saved = stem + ext
        for i in range(1, 10000):
            target = plain_path(folder / saved)
            try:
                with target.open('xb') as stream:
                    stream.write(data)
                break
            except FileExistsError:
                saved = f'{stem}-{i+1}{ext}'
        else:
            raise ValueError('同名文件过多，请换一个文件名')
        row['inputs'].append({'id': uuid.uuid4().hex, 'name': name, 'saved_name': saved,
                              'sha256': sha, 'size': len(data), 'width': width, 'height': height,
                              'mime': Image.MIME[fmt]})
        row['ready'] = False
    return mutate(manager, body.get('id'), body.get('revision'), add)


def update(manager, body):
    def save(row):
        ids = body.get('inputs', [f['id'] for f in row['inputs']])
        by_id = {f['id']: f for f in row['inputs']}
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in by_id for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('图片列表已变更，请刷新')
        row['inputs'] = [by_id[i] for i in ids]
        for field, limit in [('requirements', 16000), ('category', 48)]:
            value = body.get(field, row[field])
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError('字段长度不合法 ' + field)
            row[field] = value
        for field in ['ready', 'archived']:
            if field in body:
                if type(body[field]) is not bool:
                    raise ValueError('状态格式无效')
                row[field] = body[field]
        if row['ready'] and not row['inputs']:
            raise ValueError('至少导入一张参考图片')
    return mutate(manager, body.get('id'), body.get('revision'), save)


def prompt(manager, key):
    from .production_storage import startup_prompt
    row = get(manager, key)
    if not row['inputs']:
        raise ValueError('请先导入参考图片')
    inputs = [str(input_file(row, f)) for f in row['inputs']]
    from .material_policy import effective
    material = effective(manager, row['project'])
    text = startup_prompt(manager)['text']
    text += '\n素材持久授权\n' + json.dumps(material, ensure_ascii=False)
    text += '\n\n本次制作\n项目名称 ' + row['name'] + '\n工作流 project 绝对路径 ' + row['project']
    text += '\n输入根目录 ' + str(Path(row['workspace']) / 'input')
    text += '\n参考图按以下顺序使用\n' + '\n'.join(f'{i+1}. {p}' for i, p in enumerate(inputs))
    text += '\n制作要求\n' + (row['requirements'] or '按参考图重建为可编辑 PPT，保留文字与布局。')
    text += ('\n这些文件是用户上传后保存的原始副本。不要改写输入图片。'
             '准备工作区已存在，但 project 子目录应由 rebuild_start 创建；不要提前创建它。'
             '若 project 已有 workflow/state.json，先读取状态并续作，禁止重新初始化。'
             '所有授权与执行开关仍按工具箱当前设置检查。')
    return {'text': text, 'project': row['project'], 'inputs': inputs, 'revision': row['revision']}


def export(manager, key):
    row = get(manager, key)
    token = uuid.uuid4().hex
    directory = manager.data / 'exports'
    directory.mkdir(exist_ok=True)
    target = directory / (token + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        z.writestr('制作指令.txt', prompt(manager, key)['text'])
        z.writestr('project.json', json.dumps(row, ensure_ascii=False, indent=2))
        for item in row['inputs']:
            z.write(input_file(row, item), 'input/' + item['saved_name'])
    with manager.store.db() as c:
        c.execute('INSERT INTO exports VALUES(?,?,?,?)', (token, str(target), row['name'] + '-材料.zip', stamp()))
    return {'file_id': token, 'name': row['name'] + '-材料.zip'}
