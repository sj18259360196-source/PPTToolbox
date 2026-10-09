"""Scoped assistant evidence tools. No shell, workflow transition or adoption."""
import hashlib
import json
from pathlib import Path
from scripts import project_journal as journal
from .issue_assessment import assess, handoff
from .storage import redact

FIELDS = {
    'read_call_details': {'project':'string','call_id':'string'},
    'inspect_artifact': {'project':'string','path':'string'},
    'assess_issues': {'project':'string'},
    'prepare_handoff': {'project':'string','sequence':'integer'},
    'prepare_review_bundle': {'project':'string','sequence':'integer'},
    'validate_scene_candidate': {'project':'string','scene':'string'},
    'record_issue_disposition': {'project':'string','sequence':'integer','issue_id':'string'},
    'run_registered_checks': {'project':'string','kind':'string'},
    'draft_experience_update': {'project':'string','sequence':'integer','text':'string','evidence_id':'string'},
    'draft_tool_change': {'project':'string','sequence':'integer','text':'string','evidence_id':'string'},
}
DESCRIPTIONS = {
    'read_call_details':'读取所选项目一次调用的脱敏审计详情和持久回执，不重试。',
    'inspect_artifact':'核对项目内产物的存在性、大小与 SHA256，不读取凭据或任务 token。',
    'assess_issues':'确定性区分当前待核对和历史提示；不改变原始结果。',
    'prepare_handoff':'先 read_project，再保存当前证据交接包，供制作 Agent 减少重复查询。',
    'prepare_review_bundle':'先 read_project，再准备参考图、交付与任务检查索引；不代替看图。',
    'validate_scene_candidate':'经受管图形入口预检 scene 相对项目路径，返回合同与路径问题，不导入。',
    'record_issue_disposition':'先 read_project。仅记录程序已经判定的历史或普通提示；未知结果不能被模型关闭。',
    'run_registered_checks':'只运行 project_records 或 delivery_files 的本地只读检查，不执行任意命令。',
    'draft_experience_update':'保存有当前项目 evidence_id 的经验更新候选，发布前仍需验证与来源检查。',
    'draft_tool_change':'保存有当前项目 evidence_id 的工具改进候选，不修改程序或发布软件。',
}


def fingerprint(state):
    value={k:state.get(k) for k in ('project_id','phase','activity','files')}
    # Connection polling is not new business evidence.
    value['activity']={k:v for k,v in (value['activity'] or {}).items() if k not in {'connection','visual'}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def artifact(root, relative):
    if not isinstance(relative,str) or not relative or len(relative)>500 or Path(relative).is_absolute():
        raise ValueError('需要项目内文件路径')
    path=journal.safe(root,relative)
    if path.suffix.lower() not in {'.pptx','.png','.jpg','.jpeg','.svg','.pdf','.json','.md'}:
        raise ValueError('不支持读取此类产物')
    if path.exists() and (not path.is_file() or path.stat().st_size>512*1024*1024):
        raise ValueError('产物大小或类型不适合检查')
    if not path.is_file():return {'path':relative,'exists':False}
    with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    return {'path':relative,'exists':True,'size':path.stat().st_size,'sha256':digest}


def save(root,state,kind,body):
    packet={'kind':kind,'basis_sequence':state['sequence'],'input_fingerprint':fingerprint(state),
            'project_id':state['project_id'],'body':body,'authority':'management_candidate_only'}
    identifier=hashlib.sha256(json.dumps(packet,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    relative='.ppttool/assistance/'+identifier[:24]+'.json'
    previous=state.get('assistance',{})
    if previous.get(kind,{}).get('input_fingerprint')==packet['input_fingerprint'] and kind in {'prepare_handoff','prepare_review_bundle'}:
        return previous[kind]
    with journal.locked(root):
        current=journal.load(root)
        if current['sequence']!=state['sequence']:raise ValueError('项目已变化，请重新读取后准备')
        journal.safe(root,'.ppttool/assistance').mkdir(parents=True,exist_ok=True)
        journal.atomic(journal.safe(root,relative),json.dumps(packet,ensure_ascii=False,indent=2))
    record={'path':relative,'input_fingerprint':packet['input_fingerprint'],'basis_sequence':state['sequence'],
            'kind':kind,'created_at':journal.now()}
    result=journal.update(root,{'assistance':{**previous,kind:record}},'pptagent.assistance',source='pptagent',
                          detail={'kind':kind,'path':relative},expected_sequence=state['sequence'])
    if result.get('discarded'):raise ValueError('项目已变化，候选保留但未采用，请重新读取')
    return record


def tool(manager,name,args,scope):
    from .project_hub import entry
    key=args['project']
    if not scope or key!=scope:raise ValueError('辅助操作仅限当前选定项目')
    root,row,workflow=entry(manager,key);state=journal.load(root)
    if not state:raise ValueError('项目记录尚未初始化')
    if 'sequence' in args and args['sequence']!=state['sequence']:raise ValueError('项目已变化，请先 read_project')
    if name=='read_call_details':
        with manager.store.db() as db:
            rows=db.execute("SELECT id,time,action,status,details FROM events WHERE json_extract(details,'$.project')=? AND json_extract(details,'$.call_id')=? ORDER BY id LIMIT 24",(str(root),args['call_id'])).fetchall()
        allowed={'tool_id','call_id','command_status','error_code','error_message','recovery','revision_before','revision_after','task_id','started_at','ended_at','timings'}
        result=[{'evidence_id':'audit-'+str(e['id']),'at':e['time'],'action':e['action'],'status':e['status'],
                 'details':{k:v for k,v in json.loads(e['details'] or '{}').items() if k in allowed}} for e in rows]
        import re
        receipt=None
        if re.fullmatch('[a-f0-9]{32}',args['call_id']):
            path=journal.safe(root,'logs/tool-calls/'+args['call_id']+'/activity.json')
            if path.is_file() and path.stat().st_size<=16*1024*1024:
                saved=journal.read_json(path,{})
                if saved.get('call_id')==args['call_id']:
                    receipt={k:v for k,v in saved.items() if k in allowed}
        return {'events':redact(result),'receipt':redact(receipt),'found':bool(result or receipt)}
    if name=='inspect_artifact':return artifact(root,args['path'])
    if name=='assess_issues':return assess(state)
    if name=='validate_scene_candidate':
        from .graphics import call
        return call(manager,'scene_preflight',{'project':str(root),'scene':args['scene']},source='pptagent')
    if name=='run_registered_checks':
        if args['kind']=='project_records':
            from .project_status import graph
            return {'checks':{'identity':workflow.get('project_id',state['project_id'])==state['project_id'],
                              'graph':not graph(state)['diagnostics']},'issues':assess(state),'mutated':False}
        if args['kind']=='delivery_files':
            files=[artifact(root,f['path']) for f in state.get('phase',{}).get('artifacts',[])]
            return {'files':files,'status':'present' if files and all(f['exists'] for f in files) else 'unconfirmed','mutated':False}
        raise ValueError('仅支持 project_records 或 delivery_files')
    if name=='record_issue_disposition':
        issue=next((i for i in assess(state)['issues'] if i['id']==args['issue_id']),None)
        if not issue or issue['attention_required']:raise ValueError('此问题仍需证据核对，不能收起或宣告解决')
        # Record assessment separately; original call and incident stay intact.
        body={k:issue.get(k) for k in ('id','impact','impact_reason','evidence_id','related_evidence_ids')}
        return save(root,state,'issue-'+issue['id'],body)
    if name=='prepare_handoff':return save(root,state,name,handoff(state))
    if name=='prepare_review_bundle':
        references=[{'slide':p.get('id'),'path':p.get('reference')} for p in workflow.get('pages',[]) if p.get('reference')]
        return save(root,state,name,{'references':references,'artifacts':state.get('phase',{}).get('artifacts',[]),
                    'task':state.get('activity',{}).get('task'),'visual_review':'pending_actual_view'})
    if name in {'draft_experience_update','draft_tool_change'}:
        known={x.get('evidence_id') for x in state.get('activity',{}).get('calls',[])+state.get('activity',{}).get('issues',[])}
        if not args['text'].strip() or not args['evidence_id'] or args['evidence_id'] not in known:
            raise ValueError('更新候选需要本项目已有证据编号和具体内容')
        from scripts.rebuild_assistance import search
        related=search(args['text'][:500],limit=3,budget=2500,external_root=manager.data/'experience-library')
        return save(root,state,name,{'text':redact(args['text']),'evidence_id':args['evidence_id'],
                    'related_methods':related,'state':'candidate','publication':'project_defaults_after_validation'})
    raise ValueError('未知辅助能力')
