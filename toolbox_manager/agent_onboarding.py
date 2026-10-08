"""Copyable bootstrap instructions and explicit local CLI onboarding."""
from . import agent_setup as setup


def prompt(m,a):
    host=a.get('host','codex');state=setup.status(m,host,a.get('path'))
    argv=[setup.connection(m)['command'],'-X','utf8','-B',str(m.root/'manager.py'),
          '--data-dir',str(m.data),'agent-setup','--host',host]
    if state['target']:argv+=['--path',state['target']]
    def command(*extra):
        return '& '+' '.join("'"+str(v).replace("'","''")+"'" for v in [*argv,*extra])
    generic=host=='generic'
    text=(f'请帮助我将本机 PPT 工具箱接入当前 {setup.HOSTS[host]}。本次只处理工具箱接入，不创建项目或修改制作权限。\n\n'
          f'工具箱程序目录为 {m.root}，管理数据目录为 {m.data}。使用下面的现有安装命令，不重新下载安装工具箱。'
          '若你无法访问本机文件或执行终端命令，请直接说明，并让我使用工具箱的界面配置方式。\n\n'
          '先在 PowerShell 中检查配置与本机实例，确认目标客户端和路径确实属于当前客户端。客户端不匹配时停止，提示我重新选择。\n'
          +command()+'\n\n')
    if generic:
        text+=('这是通用 MCP 客户端，工具箱不会自动猜测配置文件位置。请根据当前客户端支持的配置入口合并以下条目；无法确认入口时告诉我具体需要的操作。保留其他服务和设置，修改前备份。\n'
               +state['snippet']+'\n\n完成配置后运行本机自检。\n'+command('--probe')+'\n\n')
    else:
        text+=(f'目标配置文件为 {state["target"]}。我授权你运行以下命令，仅写入本工具箱的 MCP 条目。命令会先备份原配置并保留其他条目，已正确配置时跳过写入。配置冲突或报错时停止并报告，不自行覆盖整个文件。\n'
               +command('--apply','--probe')+'\n\n')
    text+=('本机自检通过后，检查当前会话能否发现 PPT 工具箱 MCP 工具。如果客户端支持刷新 MCP，请刷新；如果无法刷新或需要重启，请告诉我这一步仍需手动操作，不要关闭当前对话或假报已连接。\n\n'
           '能发现工具后再运行以下命令，获取新的验证提示词；按返回内容通过当前客户端真正调用 toolbox_verify_connection 和 toolbox_context。'
           '口令有效期为 10 分钟，过期后重新生成。不得用本机自检进程或模拟客户端冒充当前 Agent 完成验证。\n'
           +command('--challenge')+'\n\n'
           '最后分别报告配置是否完成、本机自检是否通过、当前客户端是否已通过 MCP 验证，以及仍需我操作的步骤。')
    return {'host':host,'target':state['target'],'prompt':text,'automatic_config_supported':not generic}


def run(m,a):
    host=a.get('host','codex');path=a.get('path');state=setup.status(m,host,path)
    result={'scope':'configuration_and_local_probe','configuration_changed':False}
    if a.get('apply'):
        if host=='generic':raise ValueError('通用客户端请按客户端的配置入口合并 MCP 配置')
        if not state['configured']:
            result['write']=setup.apply(m,setup.plan(m,{'host':host,'path':path}))
            result['configuration_changed']=True
    if a.get('probe'):
        try:result['local_probe']=setup.probe(m)
        except Exception as exc:result.update(error=str(exc),returncode=1)
    result['status']=setup.status(m,host,path)
    if a.get('challenge') and not result.get('returncode'):
        if host!='generic' and not result['status']['configured']:
            raise ValueError('请先完成当前客户端的 MCP 配置，再生成验证提示词')
        result['verification']=setup.challenge(m,{'host':host,'path':path})
    return result
