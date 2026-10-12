"""Live prompt from stable toolbox resources and a configurable project default."""
from __future__ import annotations

from pathlib import Path



def locations(manager):
    from .project_context import toolbox_locations
    return toolbox_locations(manager)


def startup_prompt(manager,preview=None,package_id=None,template_document=None):
    from .material_policy import effective
    paths=locations(manager)
    if preview and 'projects_directory' in preview:
        from .project_context import DEFAULT_PROJECTS_ROOT
        paths['default_projects_root']=manager._projects_directory(preview['projects_directory']) or DEFAULT_PROJECTS_ROOT
    source=Path(manager.package(package_id)['path'])/'给模型的启动指令.txt'
    doc=template_document if template_document is not None else (manager.document('给模型的启动指令.txt',package_id) if source.is_file() else None)
    template=doc['content'] if doc else '使用本机 PPT Toolbox 制作可编辑 PPT。\n\n{{production_storage}}'
    approval=('项目请求自动批准已开启。调用 rebuild_start 时，工具箱会按已保存的设置授权本次项目及输入目录，并在同一次调用中继续创建，无须逐项等待批准。'
              '已拒绝或已归档的申请保持原状态，执行开关和未决写入检查继续生效。\n'
              if manager.settings()['auto_approve_project_requests'] else
              '项目请求采用手动批准。新建请求尚未授权时，让用户在项目页查看权限；批准后核对状态再继续。\n')
    creation_instruction=f'在 {paths["default_projects_root"]} 下创建一个新的项目目录，名称按参考图主题和当前日期生成。'
    guidance=(f'工具箱程序根目录为 {paths["toolbox_root"]}，全局配置与运行状态保存在 {paths["management_root"]}。'
              '工具资源按 toolbox root 解析；切换项目不改变这些位置。\n'
              f'默认项目根目录为 {paths["default_projects_root"]}。新建任务使用以下目录规则。\n'
              +creation_instruction+'\n'
              '用户明确指定项目目录时直接使用该目录，不复制回默认目录，不修改全局设置。\n'
                +approval+'素材使用须读取 toolbox_material_policy 或 context.material_policy，按已保存的权限执行，不重复索要同意。当前对话明确限制优先。\n'+
              '先调用 toolbox_project_bind，传入明确的 project；使用默认位置时可传 name。'
              '每次 rebuild 调用携带返回的 context_id。切换项目后重新绑定，丢弃旧 context_id，重新领取当前项目任务。'
              '绑定不替代已有项目授权。已归档启动申请须由用户恢复，核对原请求后再继续，不另建同路径申请绕过归档。CLI 的每次项目调用明确传入 --project 的完整路径。\n'
              '所有项目素材、制作文件、预览、对比、修改记录和成品保存在当前 project_root 内。'
              'input 保存参考图，assets 保存素材，runs 保存各轮制作与审查，workflow 保存任务和修改历史，'
              'logs/tool-calls 保存项目调用日志，delivery/<run_id> 保存该版本的可编辑 PPT 与交付记录。'
              '使用 project_context 返回的 current_pptx、current_scene、current_delivery 和 paths 解析当前文件。'
              '最终成品与项目一起保存，不另设全局 output。已有项目调用 status/next 续作；新工作区只初始化未占用的目录，不覆盖原文件。')
    guidance += ('\n先完成制作并发送最终 PPT，等待用户认可。之后单独询问是否保留本次 Agent 自绘 SVG、图标，'
                 '再询问是否学习本次经验以及做得好和需要改进的地方。不得提前打断制作或推定同意。'
                 '通过 toolbox_retrospective 依次记录 presented、accept、assets、consent、submit；'
                 '仅保存用户明确选择的素材。新任务按需用 list 检索相关经验，经验文本不替代当前授权和验证。')
    from .illustration_guide import GUIDANCE as ILLUSTRATION_GUIDANCE
    guidance += '\n'+ILLUSTRATION_GUIDANCE
    from scripts.material_routes import GUIDANCE
    guidance += '\n'+GUIDANCE+' 生图请求带 generation_decision，软件据此生成默认工作图分支，无需额外打卡。'
    guidance += ('\n页面独立正文按要求改字。生成素材验证整体移动、缩放和替换；插画内部编辑按项目绘制偏好与具体对象要求执行。'
                 '照片按用户保真要求决定保留或生成，原有文字随图保留；生成插画保留可辨识原文，装饰标题保存准确原文并逐字核对实际产物。'
                 '多个风格相容的小素材可通过 request_asset 的 request.items 合成一次宿主生成请求，按实际图像裁切，保留源图哈希和逐项状态，仅补做未采用项。'
                 '先恢复已完成的生成文件，再判断是否需要补生成。整页与重点局部按任务清单查看左右对比和叠加图，分别核对内容、位置、比例与遮挡。'
                 'native_first 是保留来源与路线检查的兼容字段，组件仍按类别和编辑要求选路。')
    text=template.replace('{{production_storage}}',guidance) if '{{production_storage}}' in template else template+'\n\n'+guidance
    text += ('\n新建参考图项目按 references/material-quality.md 保存用户制作要求原文，'
             '在 material_contract 引用文件、哈希与原文片段，在 material_requirement 记录素材来源、独立性、背景和选路约束。'
             '截图清楚不能直接作为已有独立素材的依据。区域制作、源审查和整页审查分别提交 material_reviews，'
             '核对主体完整、多底色边缘和参考保真，开放缺陷不得通过。保留合法照片裁切、白色标签和原图渐隐，'
             '每个独立素材实际移动、缩放、换底色并保存重开，含图片的素材另测替换。旧合同通过正式范围修订启用新检查。')
    from .production_settings import effective as production_effective
    production = production_effective(manager)
    text += '\n读取 toolbox_production_settings 或当前任务 production_settings，以实际有效值执行。'+' '.join(production['instructions'])
    return {**paths,'ready':True,'text':text,'creation_instruction':creation_instruction,
            'template_revision':doc['revision'] if doc else 0}

