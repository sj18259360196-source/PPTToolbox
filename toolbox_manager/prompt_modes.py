"""Short handoff prompt and a live, read-only manual backed by the full prompt."""
from pathlib import Path

BRIEF_PATH = 'references/agent-production-guide.md'
LIMIT = 1500
MODE_KEY = 'prompt:mode'
MODES = ('concise', 'professional')


def concise(manager, live):
    guide_available = (Path(manager.package()['path']) / BRIEF_PATH).is_file()
    reading = (f'再调用 toolbox_manual({{"path":"{BRIEF_PATH}"}})，读取完整制作说明。'
               '其中包含当前保存的制作要求与目录设置。'
               if guide_available else
               '当前工具包未提供制作说明，改用 toolbox_context({"profile":"full"}) 读取完整 startup_prompt。')
    beginning = ('请作为制作 Agent，使用本机 PPT Toolbox，根据我提供的参考图完成可编辑 PowerPoint，'
                 '保留原文、数字、布局和语义关系。先简要说明理解与下一步，再开始制作。\n\n'
                 '先调用 ppt_toolbox_manager 的 toolbox_context({"profile":"production"})，'
                 '核对实例、当前 Skill、权限与素材规则。'+reading+
                 '无法读取时说明缺少的连接或文档，不凭旧聊天猜规则。MCP 未加载时，从工具箱程序目录读取 references/current-desktop.md，按受管 CLI 接入。\n\n')
    paths = (f'工具箱程序 {live["toolbox_root"]}\n管理数据 {live["management_root"]}\n'
             f'默认项目位置 {live["default_projects_root"]}\n')
    ending = ('用户指定目录时使用指定位置；否则按参考图主题和日期新建独立项目。先 toolbox_project_bind，'
              '后续 rebuild 调用携带返回的 context_id。新项目走 rebuild_start；已有项目先 rebuild_status，按当前任务续作。'
              '所有素材、过程与交付保存在项目内。\n\n'
              '按 rebuild_next → rebuild_submit 执行，优先 return_next=true。读取当前任务与 must_view_files，'
              '工具预检不能代替实际看图。素材路线、字体与文本框组织按项目有效设置执行；用户当前明确要求优先。'
              '完成适用的 Office 渲染、文字核对和编辑验证，记录实际发现，不补写通过。\n\n'
              '阶段切换时打卡，说明已完成、待处理与阻塞，阶段内不逐工具汇报。返修、设置变化或恢复对话时，'
              '按制作说明回读当前状态、HANDOFF.md 与 ppttool.md；未变规则无需每次重读。'
              '遇到结果未知先查状态，不重放提交。只在缺少必要信息或授权时询问。\n\n'
              '完成后发送最终 PPT 和项目路径，说明验证结果、剩余差异与编辑限制。等待我认可后，'
              '再分别询问素材保留与经验学习。')
    text = beginning + paths + ending
    # Windows clipboard expands newlines; leave room for its CRLF representation.
    inline_paths = len(text.replace('\n', '\r\n')) <= LIMIT
    if not inline_paths:
        # Never truncate a filesystem path or a required instruction to meet the cap.
        paths = '完整程序、数据和默认项目目录读取 toolbox_context 的 instance 与 storage，以当前返回值为准。\n'
        text = beginning + paths + ending
    if len(text.replace('\n', '\r\n')) > LIMIT:
        raise ValueError('精简提示词超过 1500 字符，请检查随包模板')
    return {'text': text, 'chars': len(text), 'limit': LIMIT, 'inline_paths': inline_paths,
            'guide_path': BRIEF_PATH if guide_available else None}


def brief_document(manager, entry, base, package_id):
    from .production_storage import startup_prompt
    from .storage import digest
    live = startup_prompt(manager, package_id=package_id)
    revision = live['template_revision']
    content = (base.rstrip() + '\n\n## 当前完整制作要求\n\n'
               f'来源为给模型的启动指令.txt，修订 {revision}。目录与全局默认设置在本次读取时合并；'
               '绑定已有项目后，以该项目的实际有效设置为准。\n\n' + live['text'] + '\n')
    return {**entry, 'package_id': package_id, 'base': content, 'content': content,
            'base_sha256': digest(content), 'base_changed': False, 'customized': False,
            'revision': revision, 'history': [], 'diff': '', 'generated': True,
            'source': {'path': '给模型的启动指令.txt', 'revision': revision}}
