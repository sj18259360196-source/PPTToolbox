"""Paginated project files with independent delivery indexing."""
from pathlib import Path
from .workbench import Workbench
from .policy import plain_path
from .project_inventory import inspect

ALLOWED = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.pptx', '.pdf', '.json', '.md', '.txt'}


def listing(manager, key, group=None, offset=0, limit=100):
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError('文件分页参数无效')
    data = inspect(manager, key)
    if group == 'delivery':
        items = [{**f, 'group': 'delivery'} for f in data['deliveries']]
    else:
        if group and group not in {'input','assets','runs','workflow','logs','trials','.tmp','cache'}:
            raise ValueError('文件分类无效')
        items = [{**f, 'group': Path(f['path']).parts[0]} for f in data['files']
                 if Path(f['path']).suffix.lower() in ALLOWED
                 and (not group or Path(f['path']).parts[0] == group)]
        items.sort(key=lambda f: (0 if f['group'] == 'delivery' else 1, -f['mtime_ns'], f['path']))
    root, row, state = Workbench(manager).entry(key)
    return {'project': key, 'root': str(root), 'label': row['label'], 'status': state['status'],
            'lifecycle': data['lifecycle'], 'files': items[offset:offset + limit], 'total': len(items),
            'offset': offset, 'next_offset': offset + limit if offset + limit < len(items) else None,
            'limited': not data['complete'], 'errors': data['errors'], 'history': state.get('history', [])[-100:]}


def read(manager, key, name):
    root, _, _ = Workbench(manager).entry(key)
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('需要项目内相对路径')
    path = Workbench.path(root, name)
    if not path.is_file() or path.suffix.lower() not in ALLOWED:
        raise ValueError('文件不存在或不支持打开')
    for row in manager.store.get('workbench_projects', {}).values():
        child = plain_path(row['path'])
        if child != root and child.is_relative_to(root) and path.is_relative_to(child):
            raise ValueError('请从对应子项目打开此文件')
    if path.stat().st_size > 250 * 1024 * 1024:
        raise ValueError('文件超过 250 MB，请在项目目录中打开')
    return path


def open_local(manager, body):
    import os, subprocess
    from scripts.runtime_env import child_environment
    root, _, _ = Workbench(manager).entry(body.get('project'))
    relative = body.get('path')
    action = body.get('action', 'open')
    if action not in {'open','reveal'}: raise ValueError('打开操作无效')
    if relative:
        if not isinstance(relative,str) or Path(relative).is_absolute(): raise ValueError('需要项目内相对路径')
        path = Workbench.path(root, relative)
        if not (action == 'reveal' and path.is_dir()):
            path = read(manager, body.get('project'), relative)
    elif action == 'reveal': path = root
    else: raise ValueError('请选择文件')
    if os.name != 'nt': raise ValueError('本地打开需要 Windows 桌面')
    if action == 'reveal' and path.is_file():
        subprocess.Popen(['explorer.exe', '/select,', str(path)], shell=False, env=child_environment())
    else: os.startfile(str(path))
    return {'status':'requested','path':str(path),'message':'已请求本机程序打开'}
