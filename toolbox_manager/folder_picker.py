"""Native folder selection for the local owner's settings UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from scripts.runtime_env import child_environment, powershell_path


def pick_directory(manager, args):
    field=args.get('field')
    if field!='projects_directory':
        raise ValueError('未知的目录设置')
    initial=args.get('initial',manager.settings()[field])
    if not isinstance(initial,str) or any(ord(c)<32 for c in initial):
        raise ValueError('目录路径无效')
    if initial and not Path(initial).is_absolute():
        raise ValueError('目录需要完整路径')
    if os.name!='nt':raise ValueError('文件夹选择器需要 Windows 桌面')
    shell=powershell_path(manager.settings()['powershell_path'])
    if not shell:raise ValueError('未找到 PowerShell，无法打开文件夹选择器')
    env=child_environment(shell)
    env['PPT_TOOLBOX_PICK_FIELD']=field
    env['PPT_TOOLBOX_PICK_INITIAL']=initial
    # Values travel as environment data, never interpolated PowerShell source.
    result=subprocess.run([shell,'-NoProfile','-STA','-File',str(Path(__file__).with_name('pick_directory.ps1'))],
                          env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',
                          creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    if result.returncode:raise ValueError('文件夹选择器未能打开，请重试')
    try:selection=json.loads(result.stdout.lstrip('\ufeff'))
    except (ValueError,TypeError) as exc:raise ValueError('无法读取所选文件夹，请重试') from exc
    if selection.get('cancelled') is True:return {'cancelled':True}
    path=manager._projects_directory(selection.get('path'),field)
    if not path:raise ValueError('未选择文件夹')
    return {'cancelled':False,'path':path}
