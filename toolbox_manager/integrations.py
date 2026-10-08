"""Generate host configuration; registration is explicitly planned and backed up.
Registration publishes a local source. It does NOT claim Codex installed/enabled it.
"""
from __future__ import annotations
import json,secrets,shutil,zipfile
from pathlib import Path
from . import VERSION
from .storage import stamp,digest


def config_for(m):
    import sys
    argv=[str(m.root/'manager.py'),'--data-dir',str(m.data),'mcp']
    server={'command':sys.executable,'args':argv}
    if (m.root.parent/'agent_bridge.py').is_file() and (m.root.parent/'location.json').is_file():
        from .agent_setup import connection
        server=connection(m);argv=server['args']
    toml='[mcp_servers.ppt_toolbox_manager]\ncommand = '+json.dumps(server['command'])+'\nargs = '+json.dumps(argv)+'\nenabled = true\n'
    return {'mcp':{'mcpServers':{'ppt_toolbox_manager':server}},'codex_toml':toml,
        'codex_cli_argv':['codex','mcp','add','ppt_toolbox_manager','--',server['command'],*argv],
        'manifest':{'name':'ppt-toolbox-manager','version':VERSION,'description':'管理本地 PPT Skill、工具、指令、版本和日志；PPT 制作由 Agent 执行。','author':{'name':'PPT Toolbox'},'skills':'./skills/','mcpServers':'./.mcp.json',
        'interface':{'displayName':'PPT 工具箱管理器','shortDescription':'受管 PPT 重建、工具检索与任务记录',
        'longDescription':'在本机通过受管工作流重建、返修和验证可编辑PPT，读取任务日志与实际证据。执行和项目路径仍需用户授权。',
        'developerName':'PPT Toolbox','defaultPrompt':['读取当前工具箱上下文，核对授权与项目状态，再执行本次PPT任务。'],
        'category':'Productivity','capabilities':['Read','Write']}},
        'registration':m.store.get('registration'),'notes':['配置以本机实际 Python 和解压路径生成。移动目录后重新生成。',
        'MCP 提供 toolbox_* 读取与受管 rebuild_* 工作流；构建、Office导出和采用会写入授权项目。',
        '执行开关、目录授权和插件安装仍由用户控制，MCP不提供任意命令或自行提权入口。',
        '添加本地来源不等于在 Codex 中安装或启用；宿主中仍需刷新并确认。',
        '本工具不修改其他已安装插件的启停，不扫描或读取其他 Agent 对话。']}


def wrapper_skill(m):
    return '''---
name: ppt-toolbox-manager
description: 读取PPT工具箱当前上下文，通过受管MCP重建、返修和验证可编辑PPT，并保留项目调用日志。
---

# PPT 工具箱管理入口

先通过 MCP `toolbox_context` 读取当前启用版本、用户覆盖与工具策略，再按任务加载 `toolbox_manual` 和 `toolbox_search`。
核对 context.instance 与界面显示的数据目录一致。项目页显示授权请求、已登记项目和工作台入口。
主流程使用 `rebuild_start/next/submit/status/revise/finish`，局部操作使用 `rebuild_probe/patch/compare/adopt`；先读取实际工具 schema。
技能使用 `rebuild_skill_*`，适用性使用 `rebuild_route_*`。校准使用 `rebuild_calibrate_*`，遵守原问题累计预算。
其他已登记工具经 `toolbox_describe` 返回的 `managed_argv_prefix` 调用，保留同一数据目录。
关闭的工具不能通过改用旧副本绕开。宿主权限与用户许可仍优先。
受管MCP可触发本机Office构建、导出和读回；需要已安装PowerPoint及用户授权。生图仍由宿主提供。
先确认执行开关与项目授权，不能由Agent擅自开启。新任务使用独立项目目录，不复用验收数据。
新建请求未授权时，请用户在项目页查看权限并确认。批准不自动重试任务，继续前重新读取状态。MCP启动可按本机偏好拉起后台窗口；项目登记与调用使用同一数据目录。
start 目标必须是尚不存在的目录。素材保存在工作目录/input，项目可用尚不存在的工作目录/project；不要先创建目标目录。已有工作流应先读取status续作。
不要把导入、注册来源、路径存在或自检通过写成宿主已识别或Office已通过。

MCP未加载时，可使用本机配置生成的命令读取上下文：

```text
'''+str(__import__('sys').executable)+' "'+str(m.root/'manager.py')+'" --data-dir "'+str(m.data)+'" context\n```\n'


def write_plugin(m,dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True);config=config_for(m)
    (dest/'.codex-plugin').mkdir();(dest/'skills/ppt-toolbox-manager').mkdir(parents=True)
    (dest/'.codex-plugin/plugin.json').write_text(json.dumps(config['manifest'],ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'.mcp.json').write_text(json.dumps(config['mcp'],ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'skills/ppt-toolbox-manager/SKILL.md').write_text(wrapper_skill(m),encoding='utf-8')
    (dest/'README.md').write_text('# 本机插件接入包\n\n依赖已部署的工具箱管理器与Python。此配置含本机绝对路径，不能直接复制到另一台电脑；应在那里重新生成。注册后仍需在宿主中安装并验证。\n',encoding='utf-8')


def export_bundle(m):
    out=m.data/'exports'/('agent-config-'+secrets.token_hex(4));out.mkdir(parents=True)
    plugin=out/'ppt-toolbox-manager';write_plugin(m,plugin)
    cfg=config_for(m)
    (out/'codex-config-snippet.toml').write_text(cfg['codex_toml'],encoding='utf-8')
    (out/'generic-mcp.json').write_text(json.dumps(cfg['mcp'],ensure_ascii=False,indent=2),encoding='utf-8')
    archive=out.parent/(out.name+'.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in out.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(out))
    m.store.event('integration.exported','生成本机 Skill / MCP 配置包，未修改宿主设置')
    return m.register_export(archive)


def plan(m):
    path=m.home/'.agents/plugins/marketplace.json'
    if path.exists():
        if path.is_symlink():raise ValueError('市场文件是符号链接，拒绝自动修改')
        old=path.read_bytes()
        try:current=json.loads(old)
        except Exception:raise ValueError('现有 marketplace.json 不是有效JSON，不覆盖')
        if not isinstance(current,dict) or not isinstance(current.get('plugins',[]),list):raise ValueError('市场文件结构不支持')
    else:old=b'';current={'name':'personal-toolbox','interface':{'displayName':'本地工具箱'},'plugins':[]}
    # A unique source folder prevents replacement of an installed or pre-existing plugin source.
    suffix=secrets.token_hex(5);rel='./.agents/ppt-toolbox-sources/'+suffix+'/ppt-toolbox-manager'
    source=m.home/rel[2:]
    existing=[x for x in current.get('plugins',[]) if x.get('name')=='ppt-toolbox-manager']
    retained=[x for x in current.get('plugins',[]) if x.get('name')!='ppt-toolbox-manager']
    proposed={**current,'plugins':retained+[{'name':'ppt-toolbox-manager','source':{'source':'local','path':rel},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Productivity'}]}
    token=secrets.token_urlsafe(24);m.pending[token]={'type':'integration_plan','market':str(path),'source':str(source),'old_sha256':digest(old),'proposed':proposed}
    return {'confirm_id':token,'target':str(path),'source_dir':str(source),'old_sha256':digest(old),'will_replace_own_entry':bool(existing),
      'preserved_other_entries':len(retained),'proposed':proposed,
      'notice':'确认后仅新增此插件来源并备份市场文件，不改 config.toml，不启用插件，不安装依赖。Codex中还需刷新、安装并实测。'}


def apply(m,confirm_id):
    with m.lock:
        p=m.pending.pop(confirm_id,None)
        if not p or p.get('type')!='integration_plan':raise ValueError('注册计划已失效')
        path=Path(p['market']);now=path.read_bytes() if path.exists() else b''
        if path.is_symlink() or digest(now)!=p['old_sha256']:raise ValueError('市场文件已变化，请重新预览')
        dest=Path(p['source'])
        if dest.exists():raise ValueError('插件来源目录已存在')
        write_plugin(m,dest)
        path.parent.mkdir(parents=True,exist_ok=True)
        backup=None
        if now:
            backup=path.with_name('marketplace.backup-'+secrets.token_hex(6)+'.json');backup.write_bytes(now)
        tmp=path.with_name('marketplace.new-'+secrets.token_hex(6)+'.json')
        tmp.write_text(json.dumps(p['proposed'],ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
        result={'state':'source_registered_host_not_verified','marketplace':str(path),'source':str(dest),'backup':str(backup) if backup else None,'time':stamp()}
        m.store.set('registration',result);m.store.event('integration.registered','已注册本地插件来源；等待宿主安装与验证',details=result)
        return result
