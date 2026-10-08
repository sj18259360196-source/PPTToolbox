"""Editable production prompt backed by existing document revision history."""
from .production_storage import startup_prompt

PATH='给模型的启动指令.txt'
MARKER='{{production_storage}}'

def read(m):
    doc=m.document(PATH)
    live=startup_prompt(m)
    return {'content':doc['content'].replace(MARKER,'').strip(),'revision':doc['revision'],
            'package_id':doc['package_id'],'history':doc['history'],'base_changed':doc['base_changed'],
            'text':live['text'],'creation_instruction':live['creation_instruction'],
            'paths':{k:live[k] for k in ('toolbox_root','management_root','default_projects_root')}}

def history(m,revision):
    pid=m.package()['id']
    if type(revision) is not int or revision<0:raise ValueError('请选择历史版本')
    with m.store.db() as db:
        row=db.execute('SELECT content,revision,updated FROM doc_history WHERE package_id=? AND path=? AND revision=? ORDER BY id DESC LIMIT 1',(pid,PATH,revision)).fetchone()
    if not row:raise ValueError('历史版本不存在')
    return dict(row)

def call(m,op,a):
    if op=='read':return read(m)
    if op=='history':return history(m,int(a['revision']))
    if op not in {'save','restore','default'}:raise ValueError('未知提示词操作')
    if a.get('package_id')!=m.package()['id']:raise ValueError('当前工具包已切换，请刷新后重试')
    if op=='restore':content=history(m,a.get('restore_revision'))['content']
    elif op=='default':content=m.document(PATH)['base']
    else:
        content=a.get('content')
        if not isinstance(content,str) or not content.strip():raise ValueError('提示词内容不能为空')
        # Managed directories are generated afresh at copy time, not frozen here.
        content=content.replace(MARKER,'').strip()+'\n\n'+MARKER+'\n'
    m.save_document(PATH,content,a.get('revision'),a['package_id'])
    return read(m)
