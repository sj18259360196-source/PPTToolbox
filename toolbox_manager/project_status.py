"""Evidence-only status projection. Never executes, approves or advances a task."""
from __future__ import annotations

import copy
import re
from scripts.project_flow import STEP_TYPES

WAITING = {'permission_denied','action_required','blocked','office_busy','writer_busy',
           'awaiting_approval','waiting_input','no_results','cancelled','paused'}
SUCCESS = {'completed','succeeded','passed','ok'}


def safe_message(value):
    text = str(value or '')[:1200]
    text = re.sub(r'\bsk-[\w-]+', '[已隐藏密钥]', text)
    return re.sub(r'(?i)(bearer\s+|api[_-]?key[\s:=]+|token[\s:=]+)[^\s,;]+', r'\1[已隐藏]', text)


def call_state(call):
    status = call.get('status', '')
    recovery = call.get('recovery') or {}
    if recovery.get('outcome') == 'accepted_next_failed':
        return 'failed'
    if status == 'outcome_unknown' or recovery.get('outcome') == 'outcome_unknown':
        return 'outcome_unknown'
    if status == 'no_results':
        return 'empty'
    if status in SUCCESS:
        return 'done'
    if status in {'running','started','authorized','launched'}:
        return 'running'
    if status in WAITING or call.get('error_code') in WAITING or call.get('reason_code') in WAITING:
        return 'paused' if status == 'paused' else 'blocked'
    return 'failed'


def step_kind(tool, task_kind=''):
    tool = str(tool).replace('_', '.').replace('-', '.')
    task = str(task_kind).replace('_', '.').replace('-', '.')
    value = tool + ' ' + task
    # Prefer exact managed task semantics to broad matches on workflow.submit.
    tasks={'source.text.review':'source_text','text.fit':'text_fit','text.refine':'text_fit',
           'visual.review':'visual_review','detail.review':'detail_review',
           'office.edit.readback':'edit_verify','fragment.revise':'repair',
           'page.plan':'region_plan','region.objects':'native_draw','source.review':'source_text',
           'review.full':'visual_review','review.local':'detail_review',
           'editable.behavior':'edit_verify','reproducibility':'reproducibility','candidate':'compose','office.render':'preview'}
    if task in tasks:return tasks[task]
    if 'edit.readback' in tool:return 'edit_verify'
    if 'asset.material' in task or any(s in value for s in ('image.generation','generation.prepare','generation.ingest')):
        return 'generation'
    if tool in {'assets.crop','assets.chroma','assets.trim','assets.matte','ops.asset.layout'}:
        return 'crop'
    if tool in {'icons.search','icons.inspect','icons.stats','icons.providers'} or 'asset.search' in value:
        return 'search'
    if tool.startswith(('icons.','graphics.')) or any(s in value for s in ('asset.add','native.','material')):
        return 'material'
    if any(s in value for s in ('finish','deliver')): return 'delivery'
    if any(s in value for s in ('render','export','preview')): return 'preview'
    if any(s in value for s in ('edit.readback','validate','check','review','diff','repair','revise')): return 'review'
    if any(s in value for s in ('text','typography','layout')): return 'text'
    if any(s in value for s in ('reference','analy','segment','inspect')): return 'analysis'
    if any(s in value for s in ('plan','design')): return 'plan'
    if any(s in value for s in ('start','init','intake')): return 'intake'
    if any(s in value for s in ('compose','assemble','build','scene','import','submit')): return 'compose'
    return None


def generation_routes(workflow):
    """Read accepted asset requests and placement records; never infer a host call."""
    from scripts.common import walk_objects
    from scripts.material_routes import validate_decision
    routes=[]
    task=workflow.get('active_task') or {}
    for job in workflow.get('asset_jobs', [])[-8:]:
        request=job.get('request',{})
        if not request.get('generation_decision'):continue
        try:decision=validate_decision(request['generation_decision'])
        except ValueError:continue
        page=next((p for p in workflow.get('pages',[]) if p.get('id')==job.get('slide_id')), {})
        objects=[o for f in page.get('fragments',{}).values() for o in walk_objects(f.get('objects',[]))]
        objects += list(walk_objects((page.get('imported_slide') or {}).get('objects',[])))
        placed=[o for o in objects if o.get('kind')=='image' and job.get('asset') and o.get('asset')==job['asset']]
        routes.append({'id':job['id'],'purpose':request.get('purpose',''),'decision':copy.deepcopy(decision),
            'status':job.get('status'),'multi_icon_sheet':request.get('multi_icon_sheet',False),
            'placed':len(placed),'cropped':sum('source_crop' in o for o in placed),
            'task_id':task.get('id') if task.get('target',{}).get('job_id')==job['id'] else None})
    return routes


def generation_nodes(routes):
    import hashlib
    nodes=[]
    for route in routes[-8:]:
        decision=route['decision'];prefix='asset-'+hashlib.sha256(route['id'].encode()).hexdigest()[:12]
        parent='production'
        def add(suffix,kind,title,status,detail,status_label=None):
            nonlocal parent
            node={'id':prefix+'-'+suffix,'kind':kind,'title':title,'status':status,'after':[parent],
                  'stage':'production','source':'generation_route','route_job':route['id'],
                  'detail':detail,'evidence':'已接受的素材任务 · Agent 判断',
                  'call_task_id':route.get('task_id') if suffix=='generate' else None}
            if status_label:node['status_label']=status_label
            nodes.append(node);parent=node['id']
        if decision['basis']=='low_similarity':
            add('draw','material','SVG / 原生绘制','done','绘制稿已记录\n'+decision['drawing'])
            score=decision['similarity_pct']
            score_text=str(int(score)) if score==int(score) else str(score)
            detail=f'Agent 对该插图的相似度判断为 {score_text}%，低于 75%，已选择生图路线。'
            label=f'Agent {score_text}%'
        else:
            detail='按用户明确要求选择生图路线。'
            label='用户指定'
        add('decision','fidelity','相似度与路线判断','done',detail+'\n'+decision['reason']+'\n参考图　'+decision['reference'],label)
        done=route['status']=='completed'
        add('generate','generation','AI 生图','observed' if done else 'planned',
            route['purpose']+'\n'+('生成素材已登记，仍需核对回装效果。' if done else '等待宿主生图工具生成并提交素材；此记录不表示工具已经开始调用。'),
            '素材已登记' if done else None)
        if route['multi_icon_sheet']:
            cropped=route['cropped']>=2
            add('crop','crop','多图标裁剪','observed' if cropped else 'planned',
                f"已登记 {route['cropped']} 个独立裁剪对象。保留透明边缘并分别放入 PPT。",'裁剪已登记' if cropped else None)
        add('place','compose','放入 PPT','observed' if route['placed'] else 'planned',
            f"当前场景使用该素材的图片对象共 {route['placed']} 个，文字和连接线继续单独编辑。",'回装已登记' if route['placed'] else None)
    return nodes


def incident(call):
    status = call_state(call)
    if status not in {'blocked','failed','outcome_unknown','empty'}: return None
    code = call.get('error_code') or call.get('reason_code') or call.get('status')
    outcome = (call.get('recovery') or {}).get('outcome')
    title, action = '工具执行失败', '查看调用详情，修正原因后由制作 Agent 决定后续操作。'
    if status == 'blocked': title, action = '工作正在等待处理', '查看等待原因，处理后再继续当前任务。'
    if code == 'no_results': title, action = '尚未检索到素材', '调整检索条件，或登记改为素材制作的分支。'
    if code in {'permission_denied','awaiting_approval'}:
        title, action = '项目授权待处理', '到项目权限中核对授权，软件不会自行扩大权限。'
    if code in {'office_busy','writer_busy'}:
        title, action = 'Office 或项目写入被占用', '核对正在运行的任务与占用情况，再决定是否重试。'
    if status == 'outcome_unknown':
        title, action = '执行结果待确认', '先核对调用日志和产物是否已写入，再决定下一步。不要直接重放写入。'
    if outcome == 'accepted_next_failed':
        title, action = '提交已保存，下一步获取失败', '先读取当前任务状态；不要重新提交已经接受的内容。'
    return {**call, 'id': call['id'], 'status':status, 'title':title,
            'severity':'info' if status=='empty' else 'warning' if status=='blocked' else 'error',
            'message':safe_message(call.get('message') or code), 'next_action':action,
            'state':'open'}


def reconcile(previous, calls):
    """Only the same call, or a known task's successful retry, settles a failure."""
    issues = {i['id']:copy.deepcopy(i) for i in previous}
    context = None
    for call in sorted(calls, key=lambda c:c.get('at','')):
        found = incident(call)
        if found:
            if (not found.get('task_id') and found.get('tool')=='workflow.submit'
                and found.get('error_code')=='invalid_arguments'
                and found.get('recovery',{}).get('dispatch')=='not_dispatched'
                and context and context.get('tool')=='workflow.next' and call_state(context)=='done'
                and context.get('task_id') and context.get('project_id')
                and context.get('project')==found.get('project') and found.get('project')
                and context.get('revision_after') is not None):
                found['task_context']={k:context.get(k) for k in ('task_id','project_id','revision_after','evidence_id')}
            old = issues.get(found['id'])
            if not old or old.get('evidence_id')!=found.get('evidence_id'):
                issues[found['id']] = found
            elif found.get('task_context'):
                old['task_context']=found['task_context']
            if old and old.get('evidence_id')==found.get('evidence_id'):
                for field in ('project','project_id','revision_before','revision_after'):
                    if field in found:old[field]=found[field]
        elif call_state(call) == 'done':
            for old in issues.values():
                if old.get('state')!='open': continue
                same = old['id']==call['id']
                retry = (old['status']!='outcome_unknown' and old.get('task_id') and
                         old.get('task_id')==call.get('task_id') and old.get('tool')==call.get('tool') and
                         (old.get('recovery') or {}).get('outcome')!='accepted_next_failed' and
                         call.get('at','')>old.get('at',''))
                bound=old.get('task_context') or {}
                scoped=bool(old.get('project') and old.get('project')==call.get('project') and call.get('at','')>old.get('at',''))
                initialized=(scoped and old.get('tool')==call.get('tool')=='workflow.start'
                    and old.get('error_code')=='project_exists' and call.get('project_id')
                    and call.get('revision_after')==1 and (old.get('recovery') or {}).get('outcome')=='rejected')
                submitted=(scoped and old.get('tool')==call.get('tool')=='workflow.submit'
                    and bound.get('task_id') and bound['task_id']==call.get('task_id')
                    and bound.get('project_id')==call.get('project_id')
                    and bound.get('revision_after')==call.get('revision_before'))
                if same or retry or initialized or submitted:
                    old.update(state='resolved', resolved_by=call['id'], resolved_at=call.get('at'),
                        resolved_evidence_id=call.get('evidence_id'),
                        resolution_reason='项目已成功初始化' if initialized else '已领取任务成功提交' if submitted else '成功重试已确认')
        if call.get('tool','').startswith('workflow.') and call_state(call)=='done':
            context=call
        elif call.get('tool','').startswith('workflow.') and call.get('recovery',{}).get('dispatch')!='not_dispatched':
            context=None
    # Never discard unresolved failures when the recent-call window rolls forward.
    active = [i for i in issues.values() if i.get('state')=='open']
    closed = [i for i in issues.values() if i.get('state')!='open']
    return closed + active


def graph(state):
    """Enrich registered nodes; otherwise show observed calls beside major stages."""
    calls = state.get('activity', {}).get('calls', [])
    issues = [i for i in state.get('activity', {}).get('issues', []) if i.get('state')=='open']
    phase = state.get('phase', {})
    custom = state.get('work_graph', {}).get('nodes', [])
    all_routes = state.get('activity', {}).get('generation_routes', [])
    routes = all_routes[-4:]
    routed_tasks = {r['task_id'] for r in routes if r.get('task_id')} if not custom else set()
    templates = {t['id']:t for t in STEP_TYPES}
    nodes = copy.deepcopy(custom)
    if not nodes:
        from scripts.project_journal import STAGES
        done = {c.get('from_stage') for c in state.get('checkpoints', []) if c.get('event')=='transition'}
        previous = None
        for stage, title in STAGES:
            status = 'done' if stage in done else 'planned'
            if stage==phase.get('stage'):
                status = {'paused':'paused','blocked':'blocked','finished':'done' if phase.get('artifact_state')=='present' else 'blocked'}.get(phase.get('status'),'running')
            nodes.append({'id':stage,'title':title,'stage':stage,'after':[previous] if previous else [],
                          'status':status,'source':'stage','detail':phase.get('blocker') or phase.get('result_summary','') if stage==phase.get('stage') else ''})
            previous=stage
        # Keep task occurrences separate so a later review doesn't overwrite an
        # earlier failed review. Unresolved issues remain in the project panel.
        import hashlib
        groups={}
        for c in calls+issues:
            kind=step_kind(c.get('tool'),c.get('task_kind'))
            if kind and c.get('task_id') not in routed_tasks:
                groups.setdefault((kind,c.get('task_id')),[]).append(c)
        for (kind,task_id), observations in list(groups.items())[-16:]:
            if routes and kind=='generation':continue
            t=templates[kind]
            suffix='-'+hashlib.sha256(task_id.encode()).hexdigest()[:8] if task_id else ''
            nodes.append({'id':'observed-'+kind+suffix,'kind':kind,'title':t['title'],'stage':t['stage'],
                          'after':[t['stage']],'status':'planned','source':'observer',
                          'task_ids':[task_id] if task_id else [],
                          'evidence_ids':list(dict.fromkeys(c['evidence_id'] for c in observations if c.get('evidence_id'))),
                          'detail':'软件按任务归类，显示该任务的调用结果。制作进度以阶段打卡或 Agent 登记的步骤为准。'})
        nodes.extend(generation_nodes(routes))
        from .flow_projection import connect_suggestions, checkpoint_nodes
        nodes.extend(checkpoint_nodes(state.get('checkpoints', [])))
        nodes=connect_suggestions(nodes, continuations=phase.get('status')!='finished')
    for node in nodes:
        kind=node.get('kind'); template=templates.get(kind,{})
        node['actions']=template.get('actions',['calls','files'])
        node['evidence']={'stage':'阶段打卡','checkpoint':'制作 Agent 调整记录','observer':'软件自动采集','pptagent':'PPTAgent 整理','generation_route':'素材任务 · Agent 判断','suggested':'预设建议 · 尚无执行记录'}.get(node.get('source'),'制作 Agent 登记')
        def matches(c):
            if node.get('source')=='pptagent' and node['id'].startswith('auto-'):
                import hashlib
                return node['id']=='auto-'+hashlib.sha256(str(c.get('id')).encode()).hexdigest()[:20]
            if node.get('source')=='suggested':return False
            if node.get('source')=='checkpoint':return False
            if node.get('task_ids'):
                return c.get('task_id') in node['task_ids'] and (not kind or step_kind(c.get('tool'),c.get('task_kind'))==kind)
            if node.get('evidence_ids'):return c.get('evidence_id') in node['evidence_ids']
            if node.get('route_job'):
                return bool(node.get('call_task_id')) and c.get('task_id')==node['call_task_id']
            if c.get('task_id') in routed_tasks:return False
            if node.get('tools') and c.get('tool') in node['tools']: return True
            if kind and step_kind(c.get('tool'),c.get('task_kind'))==kind: return True
            return not custom and node.get('source')=='stage' and node.get('stage')==phase.get('stage') and not step_kind(c.get('tool'),c.get('task_kind'))
        relevant=[c for c in calls if matches(c) and (not node.get('updated_at') or c.get('at','')>=node['updated_at'])]
        problems=[i for i in issues if matches(i)]
        node['call_ids']=list(dict.fromkeys(c['id'] for c in relevant+problems))
        problems=[i for i in problems if i.get('status')!='empty' and i.get('message')!='no_results']
        if problems:
            problem=next((i for i in reversed(problems) if i['severity']=='error'),problems[-1])
            node.update(status=problem['status'], observedTool=problem.get('tool'),
                        evidence='调用异常 · '+str(problem.get('evidence_id','')), issue_ids=[i['id'] for i in problems],
                        detail=problem['title']+'\n'+problem['message']+'\n'+problem['next_action'])
            node.pop('status_label',None)
        elif relevant and node.get('status') not in {'done','skipped','replaced','paused'}:
            call=relevant[-1]; observed=call_state(call)
            node.update(observedTool=call.get('tool'), observed_at=call.get('at'))
            if observed=='running': node.update(status='running',evidence='工具正在执行')
            elif observed in {'done','empty'}:
                # A finished call never claims a phase or authored step has passed.
                # Observations have no pending check-in; only real incidents block them.
                if node.get('source')=='observer': node['status']='observed'
                node.update(evidence='关联工具调用已完成')
        node['actions']=list(dict.fromkeys(node['actions']+['calls']))
    visual=state.get('activity',{}).get('visual')
    if visual:
        for role,kind,title,stage in [('overview','visual_overview','整页主视觉','plan'),('detail','visual_detail','高清局部','production')]:
            counts=visual.get(role)
            existing=next((n for n in nodes if n.get('kind')==kind),None)
            if not existing and len(nodes)>=64:continue  # Summary remains visible beside a full custom graph.
            identifier='visual-'+role
            while any(n['id']==identifier for n in nodes):identifier+='-stats'
            node=existing if existing is not None else {'id':identifier,'kind':kind,'title':title,'stage':stage,
                'after':[stage] if any(n['id']==stage for n in nodes) else [],'source':'visual_telemetry','actions':['files','calls']}
            if existing is None:
                node['links']=[{'from':p,'relation':'grouping','basis':'recorded','label':'图片任务计数'} for p in node['after']]
            if counts:
                label=f"要求 {counts['required']} · 观察 {counts['submitted']}"
                detail=f"要求查看 {counts['required']} 张次，已提交观察 {counts['submitted']} 张次。\n记录来自任务与 Agent 回执，不代表宿主实际打开次数或视觉通过。"
                if existing is None:node.update(status='observed',status_label=label,detail=detail,evidence='视觉任务计数')
                else:node.update(visual_counts=copy.deepcopy(counts),detail=node.get('detail','')+'\n'+detail)
            else:node.update(status='blocked',status_label='统计不可用',detail=visual.get('measurement_note','图片统计暂不可用'),evidence='视觉统计异常')
            if visual.get('diagnostic_count'):
                node.update(status='failed',status_label='统计待核对',detail=node['detail']+'\n图片或记录存在异常，请查看上方图片统计。')
            if existing is None:nodes.append(node)
    from scripts.project_flow import diagnostics
    from .flow_semantics import project
    nodes=project(nodes,state.get('flow_lifecycle'))
    return {'nodes':nodes,'format':'ppttool-work-graph/1','diagnostics':diagnostics(nodes),
            'relationship_note':'按轮次与任务分组；同列不代表并行。实线为记录或明确登记，虚线为推断或建议。调用先后不等于依赖，交付后等待用户反馈。'+
                (' 旧记录仅展开最近 16 组任务，完整记录可查看调用历史。' if not custom else '')}
