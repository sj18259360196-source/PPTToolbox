"""Explicit public source export. Local history, feedback and libraries stay private."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
TREES = ['scripts','skills','toolbox','toolbox_manager','distribution','references','manager_docs','examples',
         'assets/schemas','assets/templates','assets/graphics','assets/icon-packs','tests','.codex-plugin','.github']
ROOT_FILES = ['README.md','LICENSE','THIRD_PARTY_NOTICES.md','SECURITY.md','CONTRIBUTING.md',
              '.gitignore','.gitattributes','release.json','MANAGER.json','SKILL.md',
              'manager.py','toolbox.py','requirements.txt','requirements-dev.txt',
              'requirements-optional.txt','requirements-icons.txt','requirements-graphics.txt','给模型的启动指令.txt']
EXCLUDE = {'vendor','__pycache__','.pytest_cache','.tmp','dist','checks','validation',
           'windows-handoff','node_modules'}
PRIVATE_DOCS = {'manager_docs/INSTALLATION_CONTRACT.md','manager_docs/AGENT_INTEGRATION.md',
                'manager_docs/RELEASE_1_11_0.md','manager_docs/RELEASE_1.11.1.md',
                'references/experience-ledger.json','references/experience-ledger.md',
                'references/tool-feedback.md','references/sol-quality-practice.md','references/experience-library.md',
                'references/production-process-learning.md','references/phase1-fixes.md'}
ALLOWED_SUFFIXES = {'.py','.ps1','.psm1','.cs','.json','.jsonl','.js','.mjs','.css','.html',
                    '.md','.txt','.svg','.png','.gz','.isl','.yml','.yaml','.in','.lock','.cmd'}
TEXT_SUFFIXES = ALLOWED_SUFFIXES - {'.png','.gz'}
PUBLIC_TESTS = {'test_software_updates.py','test_version_release.py','test_release_readiness.py',
                'test_bridge_upgrade.py','test_project_management.py','test_request_archive.py',
                'test_project_flow.py','test_illustration_fallback.py','test_workflow.py',
                'test_project_chain.py','test_installed_upgrade.py','test_manager.py','test_tools.py',
                'project_flow.test.mjs','projects_model.test.mjs','test_public_release.py'}
PUBLIC_TESTS.update({'test_shape_tools.py','test_shape_parameters.py','test_native_capabilities.py',
    'test_illustration_tools.py','test_native_illustration.py','test_graphics_construction.py',
    'test_payload_transport.py','test_pptagent_budget.py','test_visual_context_efficiency.py',
    'test_flow_relations.py','test_review_region_retention.py','test_element_scope.py',
    'test_managed_rebuild.py','test_phase1.py','test_local_workflow.py','phase01_driver.py',
    'test_pptagent_responses.py','pptagent_budget.test.mjs','test_stability_recovery.py',
    'test_experience_management.py','test_pptagent_metrics.py','test_project_list_preferences.py',
    'test_project_thumbnails.py','test_setup_wizard.py','test_update_process_detection.py'})
PUBLIC_TESTS.update({'test_gradient_capabilities.py','test_default_capabilities.py'})
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def allowed(relative):
    parts=Path(relative).parts
    return (not any(part in EXCLUDE for part in parts) and Path(relative).name!='AGENTS.md'
            and (parts[0]!='tests' or Path(relative).name in PUBLIC_TESTS)
            and relative not in PRIVATE_DOCS and not Path(relative).name.startswith('.env')
            and (Path(relative).suffix in ALLOWED_SUFFIXES or relative in ROOT_FILES))


def public_text(text):
    # Known development-machine literals become documented sample paths. No
    # original project documents are included or summarized by this exporter.
    text=re.sub(r'C:[/\\]+Users[/\\]+[0-9]+',r'C:/Users/Example',text,flags=re.I)
    text=re.sub(r'A:[/\\]+PPT tem',r'C:/Work/PPTProjects',text,flags=re.I)
    text=re.sub(r'A:[/\\]+PPTtoolbox[/\\]+ppt-reference-rebuild-app',r'C:/Dev/PPTToolbox',text,flags=re.I)
    text=re.sub(r'A:[/\\]+PPTtoolbox',r'C:/Dev/PPTToolbox-work',text,flags=re.I)
    text=re.sub(r'A:[/\\]+Project',r'C:/Work',text,flags=re.I)
    text=re.sub(r'A:[/\\]+\.codex',r'C:/Users/Example/.codex',text,flags=re.I)
    text=re.sub(r'D:[/\\]+[0-9]+',r'C:/Users/Example',text,flags=re.I)
    text=re.sub(r'历史记录保存在本机个人经验库。]+。','历史记录保存在本机个人经验库。',text)
    text=re.sub(r'来自\[[^\]]+\]\(\.\./validation/[^)]+\)[^。]*。','',text)
    text=re.sub(r'\[([^\]]+)\]\(<?(?:\.\./)+(?:checks|validation|docs/upgrade)/[^)]+\)',r'\1（本地验收记录未随包提供）',text)
    return text


def audit(root):
    root=Path(root)
    issues=[];files={}
    for p in sorted(root.rglob('*')):
        relative=p.relative_to(root).as_posix()
        if any(part in {'.git','__pycache__','.pytest_cache','dist','.tmp'} for part in p.relative_to(root).parts):
            continue
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400:
            issues.append({'file':relative,'reason':'linked path'});continue
        if not p.is_file():continue
        if p.suffix.lower() in {'.dpapi','.pem','.key','.pfx','.p12','.sqlite3','.db','.log','.pptx'} or p.name.startswith('.env'):
            issues.append({'file':relative,'reason':'private file type'})
        raw=p.read_bytes()
        if p.suffix in TEXT_SUFFIXES or p.name in ROOT_FILES:
            text=raw.decode('utf-8-sig')
        elif p.name.endswith('.json.gz'):
            text=gzip.decompress(raw).decode('utf-8')
        else:text=''
        if SECRET.search(text):issues.append({'file':relative,'reason':'credential pattern'})
        if re.search(r'(?:[A-Z]:[/\\]+Users[/\\]+[0-9]+|A:[/\\]+(?:PPTtoolbox|PPT tem)|[AD]:[/\\]+[0-9]+)',text,re.I):
            issues.append({'file':relative,'reason':'development-machine private path'})
        files[relative]=hashlib.sha256(raw).hexdigest()
    sources=root/'assets/experience/knowledge/sources.json'
    if sources.exists() and json.loads(sources.read_text('utf-8')):
        rows=json.loads(sources.read_text('utf-8'))
        # Only the explicitly curated method source may be publicly bundled.
        if any(row.get('source_id')!='S38' or row.get('document_type')!='bundled_method_guidance' for row in rows):
            issues.append({'file':sources.relative_to(root).as_posix(),'reason':'private experience sources'})
        else:
            from scripts.experience_library import audit as knowledge_audit
            checked=knowledge_audit(root=root)
            if checked['status']!='passed':
                issues.append({'file':sources.relative_to(root).as_posix(),'reason':'invalid default experience library','details':checked['issues']})
    return {'status':'passed' if not issues else 'failed','file_count':len(files),'issues':issues,'files':files}


def export(root,output):
    root,output=Path(root).resolve(),Path(output).resolve()
    if output.exists() or not output.is_relative_to(root/'dist'):
        raise ValueError('Use a new export directory inside this project dist')
    from distribution.builtin_experience import build as build_defaults
    if not (root/'PUBLIC_DISTRIBUTION.json').exists():build_defaults(root)
    output.mkdir(parents=True)
    candidates=[root/n for n in ROOT_FILES if (root/n).is_file()]
    for name in TREES:
        candidates += [p for p in (root/name).rglob('*') if p.is_file() and allowed(p.relative_to(root).as_posix())]
    changes=[]
    for p in candidates:
        relative=p.relative_to(root).as_posix()
        if p.is_symlink() or any(q.is_symlink() or getattr(q.lstat(),'st_file_attributes',0)&0x400
                                 for q in [p,*p.parents] if q.is_relative_to(root)):
            raise ValueError('Linked source cannot be published '+relative)
        dest=output/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if p.suffix in TEXT_SUFFIXES or relative in ROOT_FILES:
            before=p.read_text('utf-8-sig');after=public_text(before)
            if after!=before:changes.append(relative)
            dest.write_text(after,encoding='utf-8')
        else:shutil.copyfile(p,dest)
    knowledge=output/'assets/experience/knowledge';knowledge.mkdir(parents=True)
    (knowledge/'sources.json').write_text('[]\n',encoding='utf-8')
    (knowledge/'experience-ledger.jsonl').write_text('',encoding='utf-8')
    from distribution.builtin_experience import install_defaults
    default_count=install_defaults(root,output)
    recipes=json.loads((root/'assets/experience/knowledge/command-recipes.json').read_text('utf-8'))
    (knowledge/'command-recipes.json').write_text(json.dumps(recipes,ensure_ascii=False,indent=2),encoding='utf-8')
    # A public source tree has no access to the author's historical field notes.
    for name in PRIVATE_DOCS:
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        if path.suffix=='.json':path.write_text('{}\n',encoding='utf-8')
        else:path.write_text('# 本地历史记录\n\n公开发行版不附带作者的项目反馈和历史验收记录。请参阅 [使用说明](../manager_docs/USER_GUIDE.md) 与 [发行说明](../manager_docs/CHANGELOG.md)。\n',encoding='utf-8')
    public_docs={
        'references/experience-library.md':f'# 经验检索\n\n本版随包提供全部 {default_count} 条项目默认方法和 {len(recipes["commands"])} 个指令模板。后续获准更新的经验、工具和指令继续纳入项目默认能力，由构建流程检查完整性。用户已有修改与禁用设置优先。用 experience.search 查找相关经验，用 experience.show 查看动作及限制，必要时通过 experience.source 核对方法来源。每次只读取当前问题需要的条目。经验建议不授予项目权限，也不能替代当前 PPT 的验收。\n\n导入方式见 [来源经验库](../manager_docs/EXPERIENCE_LIBRARY.md)。\n',
        'references/current-desktop.md':'# 当前桌面入口\n\n正式使用从开始菜单启动 PPT Toolbox。程序、管理数据和 PPT 项目分别保存，具体位置以当前 toolbox_context 返回的 instance 与 storage 为准。新电脑需要自行配置 Agent 和 API，不使用开发机的路径。\n\n软件更新和安装位置见 [桌面安装](../manager_docs/DESKTOP_INSTALLATION.md)。\n',
        'manager_docs/INSTALLATION_CONTRACT.md':'# 安装与升级约定\n\n升级沿用已有安装、管理数据与用户选定的项目目录。不能把源码预览或便携启动当作正式安装升级。安装先检查活动调用和写入锁，保留恢复备份；项目与授权不能随程序更新重建。\n\n完成后分别验证 UI、CLI 与 MCP 的程序和数据身份，保留已有项目、API 配置和用户指令。回滚先核对数据库兼容性。\n',
        'manager_docs/AGENT_INTEGRATION.md':'# Agent 接入\n\n在设置中配置制作 Agent 的 stdio MCP，核对程序与数据身份，再在实际客户端完成连接验证。已有同名服务先核对来源，其他配置保持原样。\n\n可选的驻留 PPTAgent 使用 Responses API，配置与制作 Agent 分开，参阅 [PPTAgent](PPTAGENT.md) 和 [桌面安装](DESKTOP_INSTALLATION.md)。\n',
    }
    for name,text in public_docs.items():(output/name).write_text(text,encoding='utf-8')
    (output/'PUBLIC_DISTRIBUTION.json').write_text(json.dumps({'format':'ppttoolbox-public-source/1','private_experience_included':False,'builtin_method_count':default_count},indent=2),encoding='utf-8')
    result=audit(output)
    result['normalized_files']=changes
    if result['issues']:
        raise ValueError('Public export audit failed: '+json.dumps(result['issues'],ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.audit) if args.audit else export(ROOT,args.output)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'files','normalized_files'}},ensure_ascii=False))
    raise SystemExit(0 if report['status']=='passed' else 1)
