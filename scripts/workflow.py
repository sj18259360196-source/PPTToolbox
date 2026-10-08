"""Persistent task controller for editable PPT reconstruction.
One writer; one active Agent task. No background process, model API, OCR, or hidden approval.
"""
from __future__ import annotations
import copy
import json
import math
import os
import shutil
import sys
import uuid
from contextlib import nullcontext
from pathlib import Path
from PIL import Image
from common import (read_json, write_json, sha256, staged_directory, resolve_asset,
                    walk_objects, TASK_REVIEW_STATUSES, VERSION)
from preflight import probe
from build_pptx import build
from inspect_pptx import inspect
from compare_deck import compare_deck
from evidence_contract import required_review, image_size
from evidence_session import measured, scoped
from workflow_store import (FORMAT, WorkflowError, now, under, locked, load, save, brief,
                            page_ready, check_packet)
from workflow_scene import (keys, text, text_list, valid_plan, input_mapping, import_scene,
                            compile_fragment, assemble, freeze_scene, import_file)
from workflow_evidence import (file_record, import_render, render_local, comparison_views, final_gate)

ROOT=Path(__file__).resolve().parents[1]
REVIEW_STATUSES=set(TASK_REVIEW_STATUSES)
MANAGED_POLICY_VERSION = 1
_managed_policy = None


def set_managed_policy(policy):
    global _managed_policy
    _managed_policy = policy


def require_capabilities(*names):
    if _managed_policy is not None:
        _managed_policy.require(*names)
    elif os.environ.get('PPT_MANAGED_CALL_ID'):
        raise WorkflowError('permission_denied','Missing managed capability context; refusing internal execution')


def start(project:Path, references=None, scene_path=None, candidate=None, ratio=None,
          mapping='uniform', office=False, builder='python', in_place=False):
    require_capabilities('workflow.start','environment.probe')
    if scene_path:require_capabilities('pptx.validate')
    project=project.resolve()
    from project_directory import initialize_directory
    references=[p.resolve() for p in references or []]
    if bool(references)==bool(scene_path):raise WorkflowError('input_choice','Supply reference images OR an existing analyzed scene, not both')
    if builder not in {'python','external'}:raise ValueError('builder must be python or external')
    if candidate and not scene_path:raise ValueError('Candidate import needs its analyzed scene; do not infer content from a PPTX alone')
    with initialize_directory(project,in_place) as stage:
        for folder in ['input','assets','runs','workflow/tasks','workflow/results','workflow/archives','delivery']:(stage/folder).mkdir(parents=True)
        if scene_path:
            canvas,title,pages=import_scene(scene_path.resolve(),stage)
            if ratio:raise ValueError('Imported scenes keep their canvas; do not silently change ratio')
        else:
            if not references:raise ValueError('At least one reference image is required')
            sizes=[image_size(p) for p in references]
            w,h=sizes[0]
            if ratio:
                a,b=[float(v) for v in ratio.split(':')]
                if not all(math.isfinite(v) and v>0 for v in (a,b)):raise ValueError('Ratio must be finite and positive')
                h=w*b/a
            canvas={'width':w,'height':h,'width_pt':960,'height_pt':960*h/w,'mapping':'uniform','background':'FFFFFF'}
            title='Reference rebuild';pages=[]
            for i,(p,size) in enumerate(zip(references,sizes),1):
                rel=f'input/slide-{i:03}{p.suffix.lower()}';shutil.copyfile(p,stage/rel)
                pages.append({'id':f'slide-{i:03}','index':i,'reference':rel,'size':size,'sha256':sha256(stage/rel),
                              'mapping':input_mapping(canvas,size,mapping),'plan':None,'fragments':{},
                              'imported_slide':None,'source_review':None})
        for page in pages:
            page['native_first'] = True
        refs=[{'slide':p['index'],'path':p['reference'],'size':p['size'],'sha256':p['sha256']} for p in pages]
        write_json(stage/'input/references.json',refs)
        from project_journal import manifest
        folder_identity = manifest(project) if (project/'ppttool.md').exists() else None
        state={'format':FORMAT,'skill_version':VERSION,'product_version':VERSION,'project_id':(folder_identity or {}).get('project_id') or uuid.uuid4().hex,'revision':0,'title':title,'canvas':canvas,
               'pages':pages,'created_at':now(),'updated_at':now(),'status':'awaiting_analysis',
               'builder':'external' if candidate else builder,'office_requested':office,'active_task':None,
               'task_seq':0,'run_seq':0,'run':None,'accepted':[],'asset_jobs':[], 'failure':None,'operation':None,
               'tracked_inputs':{},'history':[]}
        if candidate:
            if candidate.suffix.lower()!='.pptx':raise ValueError('Candidate must be .pptx')
            rel=import_file(candidate,stage,'input/candidates');state['pending_candidate']=file_record(stage,stage/rel)
        for folder in ['input','assets']:
            for path in (stage/folder).rglob('*'):
                if path.is_file():state['tracked_inputs'][path.relative_to(stage).as_posix()]=sha256(path)
        write_json(stage/'workflow/preflight.json',probe())
        write_json(stage/'workflow/project-context.json',{'format':'ppt-project-context/1','project_id':state['project_id'],
                   'path_base':'project_root','input':'input','assets':'assets','versions':'runs',
                   'workflow':'workflow','logs':'logs/tool-calls','delivery':'delivery'})
        save(stage,state,'project_started',{'mode':'scene_import' if scene_path else 'reference_images','builder':state['builder']})
    return {**brief(state),'project':str(project),'next_command':['next','--project',str(project)]}


def _page(state,sid):
    for p in state['pages']:
        if p['id']==sid:return p
    raise WorkflowError('unknown_page','Unknown slide ID: '+str(sid))


def _all_source_passed(s):
    return all(page_ready(p) and p.get('source_review') and p['source_review']['status']=='passed' for p in s['pages'])


def _track_assets(project,state,objects):
    for obj in walk_objects(objects):
        if obj['kind']=='image':
            p=resolve_asset(project,obj['asset']);state['tracked_inputs'][obj['asset']]=sha256(p)


def add_asset(project:Path,source:Path,provenance:str):
    with locked(project):
        s=load(project)
        # Assets can be imported while a regional task is active; this is an explicit task amendment.
        rel=import_file(source,project);s['tracked_inputs'][rel]=sha256(project/rel)
        s.setdefault('asset_catalog',[]).append({'asset':rel,'provenance':text(provenance,'provenance'),'sha256':sha256(project/rel)})
        _cancel(s,'asset_imported')
        save(project,s,'asset_imported',{'asset':rel})
        return {**brief(s),'asset':rel,'note':'Current task was refreshed to include the new asset; call next and use its new token.'}


def _cancel(s,reason):
    if s.get('active_task'):
        s.setdefault('cancelled_tasks',[]).append({'id':s['active_task']['id'],'reason':reason})
    s['active_task']=None


def _begin(project,s,kind):
    s['operation']={'kind':kind,'at':now(),'revision':s['revision']+1}
    save(project,s,'operation_started',{'kind':kind})


def _end(project,s,kind):
    s['operation']=None;s['failure']=None;save(project,s,'operation_completed',{'kind':kind})


def _fail(project,s,kind,exc):
    s['operation']=None;s['failure']={'stage':kind,'type':type(exc).__name__,'message':str(exc),'code':getattr(exc,'code','execution_failed'),'hint':getattr(exc,'hint','See the failed stage output; correct only the affected input/operation.')}
    s['status']='tool_failed';save(project,s,'operation_failed',s['failure'])


def _inspect_candidate(project,s,path):
    require_capabilities('pptx.inspect')
    run=s['run'];scene=under(project,run['dir']+'/scene.json');report=inspect(path,scene)
    if any(v.get('status')=='failed' for v in report['checks'].values()):
        raise WorkflowError('candidate_audit_failed','Candidate does not match the current scene/native structure. Do not remove expectations to force a pass.',json.dumps(report['checks'],ensure_ascii=False)[:2500])
    reportpath=path.parent/'audit.json';write_json(reportpath,report)
    run['candidate']=file_record(project,path);run['audit']=file_record(project,reportpath)


def _progress(project,s,max_steps=6,office=None):
    if s.get('active_task') or s.get('failure') or s.get('operation') or s.get('status')=='awaiting_revision':return
    if not _all_source_passed(s):return
    if (s.get('run') or {}).get('preview') and not s['run'].get('render') and _preview_queue(project,s):return
    for _ in range(max_steps):
        run=s.get('run');kind=None
        try:
            if run is None:
                require_capabilities('pptx.validate')
                kind='freeze';_begin(project,s,kind);s['run_seq']+=1
                rid=f'run-{s["run_seq"]:04}';base=project/'runs'/rid
                with staged_directory(base) as stage:_,frozen=freeze_scene(s,project,stage)
                s['run']={'id':rid,'dir':base.relative_to(project).as_posix(),'frozen':frozen,'reviews':{},'attempt':0}
                s['status']='ready_to_build';_end(project,s,kind);continue
            base=under(project,run['dir']+'/scene.json').parent
            if not run.get('candidate'):
                if s['builder']=='external' and not s.get('pending_candidate'):
                    s['status']='awaiting_candidate';save(project,s,'awaiting_candidate');return
                require_capabilities('pptx.inspect')
                if not s.get('pending_candidate'):require_capabilities('pptx.build','pptx.validate')
                kind='candidate';_begin(project,s,kind);run['attempt']+=1
                dest=base/f'candidate-{run["attempt"]:03}';dest.mkdir()
                pptx=dest/'candidate.pptx'
                if s.get('pending_candidate'):
                    shutil.copyfile(under(project,s['pending_candidate']['file']),pptx)
                else:build(base/'scene.json',pptx)
                _inspect_candidate(project,s,pptx);s['status']='awaiting_office';_end(project,s,kind);continue
            if not run.get('render'):
                if not (s['office_requested'] if office is None else office) or os.name!='nt':
                    if s['status']!='awaiting_office':s['status']='awaiting_office';save(project,s,'awaiting_office')
                    return
                require_capabilities('office.render')
                kind='render';_begin(project,s,kind);run['attempt']+=1
                result=render_local(under(project,run['candidate']['file']),base/'scene.json',base/f'office-{run["attempt"]:03}',ROOT/'scripts/render_powerpoint.ps1')
                if result['status']!='passed':
                    s['status']='awaiting_office';s['operation']=None;save(project,s,'awaiting_office',result);return
                run['render']=file_record(project,result['receipt']);s['status']='ready_to_compare';_end(project,s,kind);continue
            if not run.get('comparison'):
                require_capabilities('compare.deck','compare.page')
                kind='compare';_begin(project,s,kind);run['attempt']+=1;out=base/f'comparisons-{run["attempt"]:03}'
                compare_deck(base/'scene.json',under(project,run['render']['file']),out,base/'regions.json',pptx_path=under(project,run['candidate']['file']))
                run['comparison']=file_record(project,out/'deck-comparison.json')
                from review_reuse import restore
                restore(project,s)
                s['status']='awaiting_visual_review';_end(project,s,kind);return
            if _review_queue(project,s):return
            if not run.get('gate'):
                require_capabilities('delivery.verify')
                kind='gate';_begin(project,s,kind);run['attempt']+=1;out=base/f'gate-{run["attempt"]:03}';out.mkdir()
                result,reviewp,gatep=final_gate(project,s,out)
                run['review']=file_record(project,reviewp);run['gate']=file_record(project,gatep)
                s['status']='ready_to_deliver' if result['status']=='passed' else 'awaiting_revision' if result['status']=='failed' else 'awaiting_review_completion'
                _end(project,s,kind);return
            return
        except Exception as exc:
            if getattr(exc,'code',None)=='permission_denied':raise
            _fail(project,s,kind or 'progress',exc);return


def advance(project:Path,office=None,max_steps=6):
    require_capabilities('workflow.advance')
    with locked(project):
        s=load(project);_progress(project,s,max_steps,office);return brief(s)


def _preview_views(project,run):
    from preview_review import validate_preview_comparisons
    pre=run['preview'];base=under(project,run['dir']+'/scene.json').parent
    return validate_preview_comparisons(under(project,pre['comparison']['file']),base/'scene.json',
        under(project,run['candidate']['file']),under(project,pre['render']['file']),base/'regions.json')


def _preview_queue(project,s):
    run=s.get('run') or {};pre=run.get('preview')
    if not pre or run.get('render'):return []
    views=_preview_views(project,run);done=pre['reviews'];queue=[]
    for page in s['pages']:
        key='preview-full:'+page['id']
        if key not in done:queue.append(('preview_full',{'slide_id':page['id'],'index':page['index'],'key':key}))
    for (idx,rid),row in sorted(views['local_paths'].items()):
        key=f'preview-local:{idx}:{rid}'
        if key not in done:queue.append(('preview_local',{'slide_id':s['pages'][idx-1]['id'],'index':idx,'region_id':rid,'key':key,'object_ids':row['object_ids']}))
    return queue


def preview(project:Path,receipt:Path|None=None,executable:Path|None=None,timeout=180):
    require_capabilities('workflow.preview','preview.compare')
    if receipt is None:require_capabilities('preview.render')
    """Explicit preview while awaiting Office. No final gate fields are populated."""
    from preview_review import render_preview,import_preview,compare_preview
    if receipt is not None and executable is not None:raise ValueError('Choose receipt import or executable rendering, not both')
    with locked(project):
        s=load(project);run=s.get('run')
        if not run or not run.get('candidate'):
            raise WorkflowError('candidate_required','Finish source review and call next to create/import a candidate first')
        if run.get('render'):
            raise WorkflowError('office_already_available','Use the actual Office comparison/review tasks for this run')
        if s.get('failure') or s.get('operation') or s['status']=='awaiting_revision':
            raise WorkflowError('pending_change','Resolve the recorded failure/revision first; preview must not clear it')
        if s.get('active_task') and s['active_task']['kind']!='office_render':
            raise WorkflowError('active_task','Complete the current task first; only a waiting Office task can switch to preview')
        number=run.get('preview_attempt',0)+1;base=under(project,run['dir']+'/scene.json').parent
        destination=base/f'preview-{number:03}'
        pptx=under(project,run['candidate']['file'])
        # One atomic operation: failure leaves the active Office task/state valid.
        with staged_directory(destination) as stage:
            if receipt:
                rp=import_preview(receipt,pptx,base/'scene.json',stage/'render')
            else:
                render_preview(pptx,base/'scene.json',stage/'render',executable,timeout)
                rp=stage/'render/preview-render.json'
            compare_preview(base/'scene.json',pptx,rp,base/'regions.json',stage/'comparison')
        if run.get('preview'):run.setdefault('old_previews',[]).append(run['preview'])
        run['preview_attempt']=number
        run['preview']={'render':file_record(project,destination/'render/preview-render.json'),
                        'comparison':file_record(project,destination/'comparison/deck-preview.json'),
                        'reviews':{},'status':'awaiting_review','renderer':'LibreOffice',
                        'office_validation':'not_run'}
        _cancel(s,'explicit_preview_requested');s['status']='awaiting_preview_review'
        save(project,s,'preview_prepared',{'path':destination.relative_to(project).as_posix(),'office_validation':'not_run'})
        return {**brief(s),'preview_directory':str(destination),
                'next_command':['next','--project',str(project.resolve())],
                'scope':'Preview review only; complete/finish still requires actual Office evidence.'}


def _review_queue(project,s):
    run=s['run'];views=comparison_views(project,run);done=run['reviews'];queue=[]
    for page in s['pages']:
        key='full:'+page['id']
        if key not in done:queue.append(('review_full',{'slide_id':page['id'],'index':page['index'],'key':key}))
    for (idx,rid),row in sorted(views['local_paths'].items()):
        key=f'local:{idx}:{rid}'
        if key not in done:queue.append(('review_local',{'slide_id':s['pages'][idx-1]['id'],'index':idx,'region_id':rid,'key':key,'object_ids':row['object_ids']}))
    for kind in ['editable_behavior','reproducibility']:
        if kind not in done:queue.append((kind,{'key':kind}))
    return queue


@measured("task_selection")
def _choose(project,s):
    if s.get('operation'):return None,'interrupted_operation'
    if s.get('failure'):return None,'tool_failed'
    if s['status']=='awaiting_revision':return None,'awaiting_revision'
    for p in s['pages']:
        if p.get('imported_slide') is None and p.get('plan') is None:return ('page_plan',{'slide_id':p['id'],'index':p['index']}),'awaiting_analysis'
    for p in s['pages']:
        if p.get('imported_slide') is not None:continue
        for r in p['plan']['regions']:
            pending=any(j['slide_id']==p['id'] and j['region_id']==r['id'] and j['status']=='pending' for j in s['asset_jobs'])
            if r['id'] not in p['fragments'] and not pending:return ('region_objects',{'slide_id':p['id'],'index':p['index'],'region_id':r['id']}),'awaiting_analysis'
    for j in s['asset_jobs']:
        if j['status']=='pending':return ('asset_material',{'job_id':j['id'],'slide_id':j['slide_id'],'index':_page(s,j['slide_id'])['index'],'region_id':j['region_id']}),'awaiting_asset_generation'
    for p in s['pages']:
        if page_ready(p) and not p.get('source_review'):return ('source_review',{'slide_id':p['id'],'index':p['index']}),'awaiting_source_review'
        if p.get('source_review') and p['source_review']['status']!='passed':return None,'awaiting_revision'
    if not _all_source_passed(s):return None,'awaiting_capability'
    if not s.get('run'):return None,'ready_to_build'
    run=s['run']
    if not run.get('candidate'):return ('candidate',{'key':'candidate'}),'awaiting_candidate'
    if not run.get('render'):
        preview_tasks=_preview_queue(project,s)
        if preview_tasks:return preview_tasks[0],'awaiting_preview_review'
        return ('office_render',{'key':'office_render'}),'awaiting_office'
    if not run.get('comparison'):return None,'ready_to_compare'
    q=_review_queue(project,s)
    if q:return q[0],'awaiting_visual_review' if q[0][0].startswith('review_') else 'awaiting_edit_check'
    return None,s['status']


def _template(kind,context):
    assertion={'status':'blocked','note':'','reviewer':'','viewed_files':[]}
    if kind=='page_plan':
        previous=context.get('previous_element_scope')
        scope=copy.deepcopy(previous) if previous else {
            'version':1,'revision':1,'task_requirement':'','units':[{
                'id':'unit-01','region_id':'region-01','owner_id':None,'semantic_role':'unknown',
                'input_form':'unknown','requirement':'','evidence':'','counterevidence':'','required_edit':'unresolved'}]}
        if previous:scope['revision']+=1
        return {'regions':[{'id':'region-01','bbox':[0,0,*context['reference_size']],'role':'content','summary':'','local_review':False}],
                'element_scope':scope,'notes':'','uncertainties':[]}
    if kind=='region_objects':
        result={'objects':[],'components':[],'source_notes':'','relationship_ids':[],'uncertainties':[],'asset_decisions':[]}
        if context.get('element_scope'):
            result['scope_bindings']=[{'unit_id':u['id'],'object_ids':[]} for u in context['element_scope']['units']
                                      if u['region_id']==context['region']['id']]
        return result
    if kind=='source_review':
        if context.get('element_scope'):
            assertion['scope_review']={'revision':context['element_scope']['revision'],
                'units':[{'unit_id':u['id'],'status':'blocked','note':''} for u in context['element_scope']['units']]}
        return assertion
    if kind=='asset_material':return {'file':'','tool_used':'','provenance':'','model_reported':None}
    if kind=='candidate':return {'file':''}
    if kind=='office_render':return {'receipt':''}
    if kind in {'review_full','preview_full'}:return {'reviewer':'','viewed_files':[], 'checks':{k:{'status':'blocked','note':''} for k in ['visual_full','raster_scope','text_geometry']},'findings':[]}
    if kind in {'review_local','preview_local'}:return {**assertion,'relationships':[{'object_id':x,'note':''} for x in context['relationships']],'findings':[]}
    return {**assertion,'files':[],'actions':[]}

TASK_HELP={
 'page_plan':('先看整页，判断视觉重点、必须完成的分区、编辑需求与难点，再选择制作顺序和素材方法。在 notes 简要说明重点及取舍，summary 写各区目标；无需固定权重或新增任务。重点区设 local_review，正文内容必须完整。bbox 为原图像素 xyxy；regions 仍按背景到前景排列，避免改变叠放顺序。',['references/analysis-and-planning.md','references/asset-policy.md'],[]),
 'region_objects':('只重建当前区域。bbox为局部裁图像素xywh，路径/端点同样用局部像素；字号和线宽已经是pt。ID只写局部短名；程序补页/区前缀、编辑类型和单位换算。没有原始数据不得虚构。复杂插画先按物品与材质拆层，弯管可查 graphics.inspect 的 surface_layers 合同。',['references/direct-operations.md','references/analysis-and-planning.md','references/asset-policy.md','references/native-illustration.md'],['ops.components','ops.component','pptx.validate','asset.request','office.native','graphics.inspect']),
 'source_review':('重新查看原图，逐项核对文字、数字、关系与分区遗漏。文件与转录一致不能替代此检查。此任务不是视觉成片验收。',['references/rendering-and-review.md'],[]),
 'asset_material':('调用宿主实际拥有的生图或授权素材工具，登记真实产物。需要透明时检查PNG的真实Alpha；纯色底可使用色键工具。不会由此Python控制器偷偷调用模型。',['references/asset-policy.md','references/assets-and-generation.md'],['host.image-generation','assets.chroma','assets.trim','assets.matte','ops.generation-prepare','ops.generation-ingest','ops.asset-layout']),
 'candidate':('用已给出的冻结scene与原图构建外部PPTX。必须保留对象ID及编辑深度；提交实际文件，控制器只导入/审查，不重新运行Python构建覆盖它。',['references/native-powerpoint.md','references/tool-runtime.md'],['office.native','pptx.inspect']),
 'office_render':('实际调用Windows PowerPoint导出当前候选文件，再提交生成的office-render.json。缺Office可运行toolbox.py preview进行独立LibreOffice预审；最终Office状态仍为待验证，不得冒认。',['references/tool-runtime.md'],['office.render']),
 'preview_full':('这是LibreOffice预审。打开带实际渲染器标签的全页左右图，分别检查视觉、图片范围和文字；填写blocked/needs_changes/passed只表示本轮预审，不能作为Office通过。',['references/preview-and-handoffs.md'],[]),
 'preview_local':('这是LibreOffice局部预审。核对轮廓、箭头、图标/插画边缘。裁切残影或明显不像时，记录具体对象并重新request_asset；本轮结论不转成Office验收。',['references/preview-and-handoffs.md','references/asset-policy.md'],[]),
 'review_full':('打开本页带标签左右图；分别核对整体视觉、截图扁平化范围、文字/几何。仅创建文件不等于已查看。不同检查分别填写。',['references/rendering-and-review.md'],[]),
 'review_local':('打开同裁切框局部左右图，先检查图标、形状、组件、背景的轮廓、数量、端点与边缘，再检查文字完整、重叠、换行和对齐。字体默认近似适配，用户明确要求原字体或特定字形时再专项检查。涉及关系时逐条填观察，不用整页平均分代替。',['references/rendering-and-review.md','references/troubleshooting.md'],[]),
 'editable_behavior':('在副本上实际修改文字和形状填充；有表格/数据图表时修改其单元格/数据，保存重开并检查。提交修改副本与动作记录，不能只声明对象存在。',['references/rendering-and-review.md'],['office.native','pptx.inspect']),
 'reproducibility':('在新目录按持久化输入和已采用脚本重建，核对文字、对象结构及可用渲染。不要求PPTX字节相同；提交重建文件/日志。未执行则blocked。',['references/deck-and-revisions.md'],['pptx.build','pptx.inspect']),
}


@measured("task_issue")
def _issue(project,s,kind,target):
    if kind in {'region_objects','asset_material'}:require_capabilities('assets.crop')
    skipped=[]
    while True:
        s['task_seq']+=1;tid=f'task-{s["task_seq"]:06}';folder=project/'workflow/tasks'/tid
        try:
            folder.mkdir()
            break
        except FileExistsError:
            # An interrupted issue can leave files without a committed task.
            # Preserve them, allocate a fresh identity, and never adopt their token.
            skipped.append(tid)
            if len(skipped)>=1000:
                raise WorkflowError('task_directory_conflict','Too many occupied task directories; inspect state and task history')
    required=[];inputs={};context={};page=_page(s,target['slide_id']) if 'slide_id' in target else None
    def include(path,must_view=False):
        rel=path.relative_to(project).as_posix();inputs[rel]=sha256(path)
        if must_view and rel not in required:required.append(rel)
        return rel
    for p in s['pages']:include(under(project,p['reference']))
    if page:
        context.update(reference_size=page['size'],slide_id=page['id'])
        context['native_first'] = page.get('native_first', False)
        from element_scope import compiled_scope
        context['element_scope'] = compiled_scope(page)
        context['previous_element_scope'] = page.get('previous_element_scope')
        for unit in (context['element_scope'] or {}).get('units', []):
            if 'source' in unit: include(under(project,unit['source']['asset']))
        notes=(page.get('plan') or page.get('review_plan') or {}).get('notes')
        if notes:context['production_notes']=notes
        if kind in {'page_plan','source_review'}:include(under(project,page['reference']),True)
        if kind in {'region_objects','asset_material'}:
            region=next(r for r in page['plan']['regions'] if r['id']==target['region_id'])
            with Image.open(under(project,page['reference'])) as im:im.crop(region['bbox']).save(folder/'reference-crop.png')
            include(folder/'reference-crop.png',True)
            # Global context is available, not forced into every local visual context.
            context['whole_page']=page['reference'];context['region']=region
            context['local_size']=[region['bbox'][2]-region['bbox'][0],region['bbox'][3]-region['bbox'][1]]
            context['coordinate_contract']={'bbox':'local_reference_pixels_xywh','path_points':'local_reference_pixels','font_and_line_width':'pt','id_prefix_added_by_program':page['id']+'.'+region['id']+'.'}
            context['available_assets']=[a for a in s.get('asset_catalog',[])][-30:]
            context['ready_sibling_ids']=[o['id'] for f in page['fragments'].values() for o in f['objects']]
            context['previous_fragment']=page.get('previous_fragments',{}).get(region['id'])
            if kind=='region_objects' and context['previous_fragment'] is not None:
                from workflow_scene import fragment_digest
                context['previous_fragment_sha256']=fragment_digest(context['previous_fragment'])
            if kind=='region_objects':
                from workflow_evidence import revision_feedback
                feedback=revision_feedback(project,s,page,region,folder,include)
                if feedback:context['revision_feedback']=feedback
        if kind=='source_review':
            if page.get('imported_slide') is not None:objs=page['imported_slide']['objects']
            else:objs=[o for r in page['plan']['regions'] for o in page['fragments'][r['id']]['objects']]
            context['text_and_tables']=[{'id':o['id'],'kind':o['kind'],'text':o.get('text'), 'runs':o.get('runs'),'paragraphs':o.get('paragraphs'),'rows':o.get('rows')} for o in walk_objects(objs) if o['kind'] in {'text','table'}]
            context['relations']=required_review({'objects':objs})['relationship_objects']
            context['regional_notes']=[{'id':rid,'source_notes':f['source_notes'],'uncertainties':f['uncertainties'],'asset_decisions':f.get('asset_decisions',[])} for rid,f in page['fragments'].items()]
            context['raster_inventory']=[{k:o.get(k) for k in ('id','asset','asset_role','raster_content','raster_reason')}
                for o in walk_objects(objs) if o['kind']=='image']
    if kind=='asset_material':context['request']=next(j for j in s['asset_jobs'] if j['id']==target['job_id'])['request']
    run=s.get('run')
    if run:
        include(under(project,run['dir']+'/scene.json'));context['run_dir']=run['dir'];context['scene']=run['dir']+'/scene.json'
        if run.get('candidate'):context['candidate']=include(under(project,run['candidate']['file']))
        if run.get('audit'):context['audit']=include(under(project,run['audit']['file']))
        if kind=='office_render':
            base=project/run['dir'];sizes=[{'index':p['index'],'width':p['size'][0],'height':p['size'][1]} for p in s['pages']]
            write_json(folder/'render-sizes.json',sizes);include(folder/'render-sizes.json')
            context['render_arguments']=['-Pptx',context['candidate'],'-OutputDir',run['dir']+'/host-office-'+tid,'-SizesJson',(folder/'render-sizes.json').relative_to(project).as_posix()]
        if kind in {'review_full','review_local','preview_full','preview_local'}:
            is_preview=kind.startswith('preview_')
            comp=_preview_views(project,run) if is_preview else comparison_views(project,run)
            source=run['preview'] if is_preview else run
            include(under(project,source['comparison']['file']))
            if is_preview:
                include(under(project,source['render']['file']))
                context['renderer']='LibreOffice'
                context['review_scope']='preview_only'
                context['office_validation']='not_run'
            if kind in {'review_full','preview_full'}:include(comp['full_paths'][target['index']],True)
            else:
                row=comp['local_paths'][(target['index'],target['region_id'])];include(row['file'],True)
                must=required_review(read_json(project/run['dir']/'scene.json')['slides'][target['index']-1])['relationship_objects']
                context['relationships']=sorted(set(row['object_ids'])&set(must))
                context['object_ids']=row['object_ids']
            if not is_preview:
                from workflow_evidence import text_geometry_hints
                receipt = under(project, run['render']['file'])
                context['office_render_receipt'] = include(receipt)
                context['text_geometry_hints'] = text_geometry_hints(
                    read_json(receipt), target['index'], context.get('object_ids'))
                from raster_occlusion import hints as raster_hints
                context['raster_occlusion_hints']=raster_hints(read_json(project/run['dir']/'scene.json'),
                    project/run['dir'],read_json(receipt),target['index'])
            if kind == 'review_full':
                slide = read_json(project/run['dir']/'scene.json')['slides'][target['index']-1]
                context['raster_inventory'] = [{k:o.get(k) for k in ('id','asset','asset_role','raster_content','raster_reason')}
                    for o in walk_objects(slide['objects']) if o['kind']=='image']
                must = set(required_review(read_json(project/run['dir']/'scene.json')['slides'][target['index']-1])['relationship_objects'])
                bundle = []
                for (index, rid), row in sorted(comp['local_paths'].items()):
                    key = f'local:{index}:{rid}'
                    if index != target['index'] or key in run['reviews']:
                        continue
                    bundle.append({'region_id': rid, 'key': key, 'file': include(row['file']),
                                   'object_ids': row['object_ids'],
                                   'relationships': sorted(set(row['object_ids']) & must)})
                    if len(bundle) == 6:
                        break
                context['review_bundle'] = bundle
                context['review_bundle_rule'] = ('After viewing each local file, submit additional_reviews with one independent review_local result per region_id. '
                    'Only these regions on this page are allowed. Omitted regions remain pending. No default pass or copied observations.')
        if kind in {'editable_behavior','reproducibility'}:
            scene=read_json(project/run['dir']/'scene.json');kinds={o['kind'] for slide in scene['slides'] for o in walk_objects(slide['objects'])}
            context['required_edit_actions']=([k for k in ['text','shape','table','chart'] if k in kinds] if kind=='editable_behavior' else ['rebuild'])
            context['render_note']='Review assertions need actual actions; receipt existence is not a proof of execution.'
    if kind=='region_objects':
        from components import CATALOG
        context['component_recipes']={k:{'title':v['title'],'params':v['params']} for k,v in CATALOG.items()}
        context['component_submission']='components:[{id,recipe,bbox,params?,style?}] uses the SAME local pixels as objects; primitives are compiled before unit/ID conversion. A components-only response may keep objects:[]. Default draw order is components then objects (labels above). Use optional draw_order with all top-level IDs once, back-to-front, when backgrounds/connectors require another stacking order.'
    from task_contracts import constraints, examples
    task_constraints=constraints(kind,context)
    task_examples=examples(kind,context)
    if task_constraints:context['submission_constraints']=task_constraints
    if task_examples:
        write_json(folder/'response.examples.json',task_examples)
        include(folder/'response.examples.json')
    instruction,docs,tools=TASK_HELP[kind]
    # Copy shared lists: task-specific suggestions must not leak into later tasks.
    docs=list(docs);tools=list(tools)
    from rebuild_assistance import task_advice, production_guidance
    guidance=production_guidance(kind)
    if guidance:context['production_guidance']=guidance
    reason=''
    for event in reversed(s.get('history', [])):
        detail=event.get('detail', {})
        if (event.get('event')=='region_reopened' and detail.get('slide_id')==target.get('slide_id')
                and detail.get('region_id') in (None,target.get('region_id'))):
            reason=detail.get('reason','');break
    advice=task_advice(kind,context,reason) if _managed_policy is None or 'experience.search' in _managed_policy.allowed else None
    if advice:
        context['assistance']=advice
        context['experience_usage']='若实际参考某条经验，可调用 toolbox_usage action=cite，附经验 id、本项目、task_id、具体用途及 object_ids。仅阅读或被推荐时不记为任务引用。'
        tools.append('experience.search')
        docs.append('references/codex-assistance.md')
    if kind=='region_objects' and _managed_policy is not None and 'workflow.skill_search' in _managed_policy.allowed:
        from skill_library import library_root, search
        try:
            learned=search(library_root(), str(context.get('region',{}).get('summary','native card')))
            if learned:context['learned_skills']=learned
        except (ValueError, OSError):
            context['learned_skills_status']='unavailable; use ordinary reconstruction'
    if kind=='editable_behavior':
        from office_edit import CONTRACTS
        context['edit_readback']={
            'tool':'office.edit-readback','contracts':CONTRACTS,'index_base':1,
            'targets':[{'slide':idx,'name':o['id'],'kind':o['kind']}
                       for idx,slide in enumerate(scene['slides'],1) for o in walk_objects(slide['objects'])
                       if o['kind'] in {'text','shape','table'}][:30],
            'note':'先 describe 查看字段，使用真实对象名称和不同的新值。run 在新目录修改副本并保存重开读回；查看导出图后提交原有 actions/files。图表与长文本排版仍需另测。',
        }
        tools.append('office.edit-readback')
    token=uuid.uuid4().hex
    packet={'format':'ppt-task/1.2','task_id':tid,'token':token,'kind':kind,'target':target,
            'project_id':s['project_id'],'base_revision':s['revision']+1,'instructions':instruction,
            'context':context,'required_view_files':required,'references':docs,'suggested_tools':tools,
            'input_files':[{'file':k,'sha256':v} for k,v in sorted(inputs.items())],
            'submit_protocol':'Edit result only in response.template.json; preserve task_id/token. submit validates then commits. Never edit packet/state.',
            'asset_request_alternative':({'action':'request_asset','request':{'id':'asset-01','purpose':'','prompt':'','transparent':True,'allowed_approximation':True}} if kind=='region_objects' else None)}
    write_json(folder/'packet.json',packet);write_json(folder/'response.template.json',{'task_id':tid,'token':token,'result':_template(kind,context)})
    lines=['# 当前任务 '+tid,'',instruction,'','## 先查看','']+[f'- `{p}`' for p in required]+['','## 当前所需手册','']+[f'- `{p}`' for p in docs]+['','完整参数与当前局部数据见 packet.json。只修改 response.template.json 的 result，再通过 toolbox.py submit 提交。','等待宿主工具时不填通过；输入不合法时原任务仍有效，不必重建全页。']
    if task_constraints:
        lines += ['','## 当前字段约束','',json.dumps(task_constraints,ensure_ascii=False,indent=2)]
    if task_examples:lines += ['','格式示例见 response.examples.json；不得把示例占位路径当成真实素材。']
    (folder/'TASK.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    s['active_task']={'id':tid,'kind':kind,'target':target,'token':token,'base_revision':packet['base_revision'],
                      'packet':(folder/'packet.json').relative_to(project).as_posix(),'packet_sha256':sha256(folder/'packet.json'),
                      'inputs':packet['input_files']}
    detail={'id':tid,'kind':kind}
    if skipped:detail['preserved_uncommitted_task_directories']=skipped
    save(project,s,'task_issued',detail)
    from usage_store import worker_record, key as usage_key
    for hit in (advice or {}).get('experience',{}).get('matches',[]):
        worker_record(usage_key('task-retrieval',str(project),tid,hit['id']), 'experience',hit['id'],'retrieved',project=str(project),task=tid,evidence={'scope':'included in issued task'})


def _public_task(project,s):
    result=brief(s);task=s.get('active_task')
    if task:
        check_packet(project,s,task);p=read_json(under(project,task['packet']));folder=(project/task['packet']).parent
        result.update(task={'id':task['id'],'kind':task['kind'],'target':task['target'],
            'packet':str((project/task['packet']).resolve()),'instructions':p['instructions'],
            'response_template':str((folder/'response.template.json').resolve()),
            'must_view_files':[str((project/f).resolve()) for f in p['required_view_files']],
            'read_only_when_needed':[str((ROOT/f).resolve()) for f in p['references']],
            'suggested_tools':p['suggested_tools'], 'submission_constraints':p['context'].get('submission_constraints',{}), 'examples_file':str(folder/'response.examples.json') if (folder/'response.examples.json').exists() else None, 'context_chars':len(json.dumps(p['context'],ensure_ascii=False))})
    if task:
        result['submit_argv']=[sys.executable,str(ROOT/'toolbox.py'),'submit','--project',str(project.resolve()),'--response',result['task']['response_template']]
        result['next_argv']=[sys.executable,str(ROOT/'toolbox.py'),'next','--project',str(project.resolve())]
        if task['kind'] == 'review_full':
            result['task']['review_bundle'] = [
                {**row, 'file': str((project/row['file']).resolve())}
                for row in p['context'].get('review_bundle', [])]
        if task['kind']=='office_render':
            args=p['context']['render_arguments'];resolved=[]
            for i,value in enumerate(args):
                resolved.append(str((project/value).resolve()) if i%2 else value)
            result['tool_commands']=[{'tool_id':'office.render','argv':[sys.executable,str(ROOT/'toolbox.py'),'tools','run','office.render','--',*resolved],
                                     'needs':'Actual Windows PowerPoint; paths are resolved for this current host, not the previous machine.'}]
            result['preview_alternative_argv']=[sys.executable,str(ROOT/'toolbox.py'),'preview','--project',str(project.resolve())]
            result['preview_note']='Optional LibreOffice pre-review. This does not satisfy or replace the Office gate.'
    if s.get('run'):result['run_directory']=str((project/s['run']['dir']).resolve())
    reuse=(s.get('run') or {}).get('reused_observations')
    if reuse:result['reused_observations']={'count':len(reuse['records']),'sources':reuse.get('sources'),
                                         'scope':reuse['scope']}
    if s['status']=='awaiting_revision':result['next_hint']='Use revise with explicit slide/region and reason, or replace-candidate for external changes. Previous evidence is preserved and invalidated for the new run.'
    return result


@scoped
def next_task(project:Path):
    require_capabilities('workflow.next')
    from project_journal import requirement
    checkpoint_needed = requirement(project)
    if checkpoint_needed:
        return {**brief(load(project)), 'checkpoint_required': checkpoint_needed}
    with locked(project):
        s=load(project)
        if s.get('active_task'):return _public_task(project,s)
        _progress(project,s)
        selected,status=_choose(project,s)
        if selected:
            s['status']=status;_issue(project,s,*selected)
        return _public_task(project,s)


def status(project:Path):
    require_capabilities('workflow.status')
    # A read-only status never claims to repair a writer/interruption.
    s=load(project);return _public_task(project,s)


def _seen(project,packet,result):
    viewed=result.get('viewed_files')
    if not isinstance(viewed,list) or any(not isinstance(v,str) for v in viewed):raise ValueError('viewed_files must name actual files opened with the host view tool')
    resolved=[]
    for value in viewed:
        p=Path(value)
        if not p.is_absolute():p=under(project,value)
        else:p=p.resolve()
        resolved.append(p)
    needed={(project/v).resolve() for v in packet['required_view_files']}
    if not needed<=set(resolved):raise ValueError('Missing required viewed_files; open each supplied full/local reference and record its path')


def _assertion(result, optional=()):
    keys(result,['status','note','reviewer','viewed_files'],optional)
    if result['status'] not in REVIEW_STATUSES:raise ValueError('status must be passed, needs_changes or blocked; not_applicable is derived by the controller')
    text(result['note'],'note');text(result['reviewer'],'reviewer')


@measured("response_validation")
def _accept_result(project,s,t,packet,result,*,validate_only=False):
    kind=t['kind'];target=t['target'];attachments=[]
    page=_page(s,target['slide_id']) if 'slide_id' in target else None
    if kind=='page_plan':
        plan=valid_plan(result,page['size'])
        from element_scope import validate_plan
        scope=plan.get('element_scope')
        previous=page.get('previous_element_scope')
        if previous and (scope is None or scope['revision'] <= previous['revision']):
            raise ValueError('element_scope: replan must retain obligations with an increased revision')
        if previous and not {u['id'] for u in previous['units']} <= {u['id'] for u in scope['units']}:
            raise ValueError('element_scope: replan cannot silently drop existing source obligations')
        if scope is not None:
            validate_plan(scope, project=project)
            for unit in scope['units']:
                if 'source' in unit:
                    s['tracked_inputs'][unit['source']['asset']] = unit['source']['sha256']
        page['plan']=plan
        page['planning_state']='valid'
    elif kind=='region_objects':
        if isinstance(result,dict) and result.get('action') in {'request_asset','request_assets'}:
            batch=result['action']=='request_assets'
            keys(result,['action','requests' if batch else 'request'])
            requests=result['requests'] if batch else [result['request']]
            if not isinstance(requests,list) or not 1<=len(requests)<=8:raise ValueError('Asset requests require 1..8 items')
            from workflow_scene import identifier
            pending=[];ids={j['id'] for j in s['asset_jobs']}
            for r in requests:
                keys(r,['id','purpose','prompt','transparent','allowed_approximation'],['generation_decision','multi_icon_sheet','scope_unit_ids'])
                scope=(page.get('plan') or {}).get('element_scope')
                if scope is not None:
                    units={u['id']:u for u in scope['units'] if u['region_id']==target['region_id']}
                    requested=r.get('scope_unit_ids')
                    if (not isinstance(requested,list) or not requested or any(not isinstance(x,str) for x in requested)
                            or len(requested)!=len(set(requested)) or any(x not in units for x in requested)):
                        raise ValueError('element_scope: generation requires current regional scope_unit_ids')
                    if any(units[x]['required_edit'] in {'preserve','unresolved'} for x in requested):
                        raise ValueError('element_scope: preserved or unresolved sources cannot be regenerated')
                identifier(r['id'],'asset job id');text(r['purpose'],'asset purpose');text(r['prompt'],'asset prompt')
                if type(r['transparent']) is not bool or r['allowed_approximation'] is not True:raise ValueError('Generated substitution needs an explicit allowed_approximation decision')
                if 'multi_icon_sheet' in r and type(r['multi_icon_sheet']) is not bool:raise ValueError('multi_icon_sheet must be boolean')
                if 'generation_decision' in r:
                    from material_routes import validate_decision
                    validate_decision(r['generation_decision'],project)
                    if not r['transparent']:raise ValueError('Illustration fallback requires a transparent PNG')
                jid=f'{page["id"]}.{target["region_id"]}.{r["id"]}'
                if jid in ids:raise ValueError('Asset job ID already used; choose a new one')
                ids.add(jid)
                pending.append({'id':jid,'slide_id':page['id'],'region_id':target['region_id'],'request':r,'status':'pending'})
            s['asset_jobs'].extend(pending)
        else:
            require_capabilities('pptx.validate')
            if result.get('action')=='revise_objects':
                from workflow_scene import merge_fragment_revision
                result=merge_fragment_revision(
                    page.get('previous_fragments',{}).get(target['region_id']),result)
            if result.get('components'):require_capabilities('ops.component')
            region=next(r for r in page['plan']['regions'] if r['id']==target['region_id'])
            frag=compile_fragment(page,region,result,s['canvas'],project);_track_assets(project,s,frag['objects'])
            page['fragments'][region['id']]=frag;page['source_review']=None
    elif kind=='asset_material':
        keys(result,['file','tool_used','provenance'],['model_reported']);text(result['tool_used'],'actual tool');text(result['provenance'],'provenance')
        src=Path(result['file']).resolve();job=next(j for j in s['asset_jobs'] if j['id']==target['job_id'])
        with Image.open(src) as im:
            im.load()
            if im.format!='PNG':raise ValueError('Host raster substitution currently requires actual PNG content; SVG is a separate native/vector route')
            if job['request']['transparent']:
                if 'A' not in im.getbands() or im.getchannel('A').getextrema()[0]>=255 or im.getchannel('A').getextrema()[1]==0:raise ValueError('Requested transparency needs nonempty visible content AND genuinely transparent pixels')
        if validate_only:return attachments
        rel=import_file(src,project);s['tracked_inputs'][rel]=sha256(project/rel)
        info={'asset':rel,'provenance':result['provenance'],'tool_used':result['tool_used'],'model_reported':result.get('model_reported'), 'source_kind':'generated','job_id':job['id']}
        for field in ('generation_decision','multi_icon_sheet'):
            if field in job['request']:info[field]=copy.deepcopy(job['request'][field])
        s.setdefault('asset_catalog',[]).append(info);job.update(status='completed',asset=rel)
    elif kind=='source_review':
        _assertion(result, ('text_checks','scope_review'));_seen(project,packet,result)
        from source_text_review import validate_text_checks
        objs = (page['imported_slide']['objects'] if page.get('imported_slide') is not None
                else [o for r in page['plan']['regions'] for o in page['fragments'][r['id']]['objects']])
        validate_text_checks(result, objs)
        from element_scope import compiled_scope, validate_review
        validate_review(compiled_scope(page), result, objs, project)
    elif kind=='candidate':
        require_capabilities('pptx.inspect')
        keys(result,['file']);src=Path(result['file']).resolve()
        if src.suffix.lower()!='.pptx':raise ValueError('Only .pptx candidates supported')
        run=s['run']
        if validate_only:
            report=inspect(src,under(project,run['dir']+'/scene.json'))
            if any(v.get('status')=='failed' for v in report['checks'].values()):
                raise ValueError('External candidate differs from the frozen scene')
            return attachments
        run['attempt']+=1;dest=project/run['dir']/f'external-{run["attempt"]:03}'
        with staged_directory(dest) as stage:
            dst=stage/'candidate.pptx';shutil.copyfile(src,dst)
            report=inspect(dst,under(project,run['dir']+'/scene.json'))
            if any(v.get('status')=='failed' for v in report['checks'].values()):
                raise ValueError('External candidate differs from the frozen scene: '+json.dumps(report['checks'],ensure_ascii=False)[:1800])
            write_json(stage/'audit.json',report)
        run['candidate']=file_record(project,dest/'candidate.pptx');run['audit']=file_record(project,dest/'audit.json')
    elif kind=='office_render':
        require_capabilities('office.render')
        keys(result,['receipt']);run=s['run']
        if validate_only:
            from evidence_contract import validate_render
            validate_render(Path(result['receipt']),under(project,run['candidate']['file']),len(s['pages']))
            return attachments
        run['attempt']+=1
        receipt=import_render(Path(result['receipt']),under(project,run['candidate']['file']),project/run['dir']/f'office-import-{run["attempt"]:03}',len(s['pages']))
        run['render']=file_record(project,receipt)
    elif kind in {'review_full','preview_full'}:
        keys(result,['reviewer','viewed_files','checks'],['findings','additional_reviews'] if kind == 'review_full' else ['findings']);text(result['reviewer'],'reviewer');_seen(project,packet,result)
        keys(result['checks'],['visual_full','raster_scope','text_geometry'])
        for c in result['checks'].values():
            keys(c,['status','note']);text(c['note'],'check note')
            if c['status'] not in REVIEW_STATUSES:raise ValueError('Each check needs passed/needs_changes/blocked')
        if 'additional_reviews' in result:
            rows = result['additional_reviews']
            allowed = {row['region_id']: row for row in packet['context'].get('review_bundle', [])}
            if not isinstance(rows, list) or not 1 <= len(rows) <= 6:
                raise ValueError('additional_reviews requires 1..6 independently viewed local reviews')
            seen = set()
            for row in rows:
                keys(row, ['region_id', 'result'])
                rid = row['region_id']
                if rid not in allowed or rid in seen:
                    raise ValueError('Additional review region is duplicate or outside the issued page bundle')
                seen.add(rid)
                item = allowed[rid]
                local_task = {**t, 'kind': 'review_local', 'target': {**target, 'region_id': rid, 'key': item['key']}}
                local_packet = {'required_view_files': [item['file']], 'context': {'relationships': item['relationships']}}
                _accept_result(project, s, local_task, local_packet, row['result'], validate_only=True)
    elif kind in {'review_local','preview_local'}:
        _assertion(result,['relationships','findings']);_seen(project,packet,result)
        rows=result.get('relationships',[])
        if not isinstance(rows,list):raise ValueError('relationships must be a list')
        names=[]
        for row in rows:
            keys(row,['object_id','note']);text(row['note'],'relationship observation');names.append(row['object_id'])
        if len(names)!=len(set(names)) or set(names)!=set(packet['context']['relationships']):raise ValueError('Review each required relationship object exactly once')
    elif kind in {'editable_behavior','reproducibility'}:
        _assertion(result,['files','actions']);_seen(project,packet,result)
        if not isinstance(result.get('actions'),list):raise ValueError('actions must be a list')
        for a in result['actions']:keys(a,['kind','note'],['object_id','slide_id']);text(a['note'],'action note')
        if result['status']=='passed':
            needed=set(packet['context']['required_edit_actions'])
            if not needed<={a['kind'] for a in result['actions']}:raise ValueError('Action record does not cover required edit/rebuild kinds')
            if not result.get('files'):raise ValueError('Passing edit/rebuild review needs actual output files, not just an assertion')
            paths=[Path(f).resolve() for f in result['files']]
            pptxs=[p for p in paths if p.suffix.lower()=='.pptx']
            if not pptxs:raise ValueError('Attach at least one actual edited/rebuilt PPTX copy')
            current=under(project,s['run']['candidate']['file'])
            if any(p==current for p in paths):raise ValueError('Do not use or modify the current candidate as the edit/rebuild test')
            if kind=='editable_behavior' and not any(sha256(p)!=sha256(current) for p in pptxs):raise ValueError('Edited test PPTX must differ from the candidate')
            if kind=='editable_behavior':
                for p in paths:
                    if p.suffix.lower()=='.json' and p.stat().st_size<=4_000_000:
                        try:edit_receipt=read_json(p)
                        except (ValueError,UnicodeError):continue
                        if (isinstance(edit_receipt,dict) and edit_receipt.get('format')=='ppt-edit-readback/1'
                                and edit_receipt.get('longer_text_layout')=='overflow_detected'):
                            raise ValueError('Longer text overflow is unresolved; submit needs_changes rather than passed')
            for p in pptxs:
                require_capabilities('pptx.inspect')
                report=inspect(p)
                if report['checks']['package']['status']!='passed':raise ValueError('Attached PPTX is not a readable audited package')
            if validate_only:
                for p in paths:sha256(p)
                return attachments
            for p in paths:
                rel=import_file(p,project,s['run']['dir']+'/agent-evidence');attachments.append(file_record(project,project/rel))
    else:raise ValueError('Unknown task kind')
    return attachments


@scoped
def validate_response(project:Path,response:dict,expected_revision=None):
    """Read-only result validation. Managed audit logs are separate from workflow state."""
    require_capabilities('workflow.validate_response')
    from jsonschema import Draft202012Validator
    from toolbox_manager.contracts import result_contracts
    before=sha256(project/'workflow/state.json')
    if (project/'workflow/writer.lock').exists():raise WorkflowError('writer_busy','A writer is active; retry validation after it completes')
    s=load(project);t=s.get('active_task')
    if not t:raise WorkflowError('no_active_task','No active task to validate')
    check_packet(project,s,t);keys(response,['task_id','token','result'])
    if response['task_id']!=t['id'] or response['token']!=t['token'] or (expected_revision is not None and expected_revision!=t['base_revision']):
        raise WorkflowError('stale_task','Task identity changed; read the current task')
    contracts,defs=result_contracts(ROOT)
    validator=Draft202012Validator({**contracts[t['kind']],'$defs':defs})
    errors=[]
    def collect(error):
        if error.context:
            for child in error.context:collect(child)
        else:
            errors.append({'path':'/result/'+ '/'.join(str(x).replace('~','~0').replace('/','~1') for x in error.absolute_path),
                           'constraint':str(error.validator), 'message':error.message[:1200],
                           'expected':error.validator_value if error.validator in {'enum','required','type'} else None})
    for error in validator.iter_errors(response['result']):collect(error)
    if not errors:
        result=copy.deepcopy(response['result'])
        if _managed_policy is not None:result=_managed_policy.result_paths(result,t['kind'])
        try:_accept_result(project,copy.deepcopy(s),t,read_json(under(project,t['packet'])),result,validate_only=True)
        except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
            if getattr(exc,'code',None)=='permission_denied':raise
            message=str(exc)
            field='viewed_files' if 'viewed_files' in message else 'objects' if 'object ID' in message else 'relationships' if 'relationship' in message else ''
            errors.append({'path':'/result'+('/'+field if field else ''),'constraint':'semantic','message':message[:1200]})
    if before!=sha256(project/'workflow/state.json') or (project/'workflow/writer.lock').exists():
        raise WorkflowError('stale_task','Workflow changed during validation; read current task')
    return {**brief(s),'valid':not errors,'errors':errors[:30],'task_consumed':False,'office':'not_run',
            'scope':'Contract and referenced files only; does not attest that images were viewed'}


def revision_candidate(project:Path,args:dict):
    require_capabilities('workflow.revision_candidate')
    with locked(project):
        s=load(project);run=s.get('run');text(args['reason'],'revision reason')
        if s['revision']!=args['base_revision']:raise WorkflowError('stale_task','Revision changed')
        if s['status']!='delivered' or not run or run['id']!=args['run_id']:
            raise WorkflowError('invalid_operation','Select the current delivered run')
        if s.get('active_task') or s.get('operation'):raise WorkflowError('writer_busy','Finish the current task first')
        page=_page(s,args['slide'])
        if not page.get('plan') or args['region'] not in {r['id'] for r in page['plan']['regions']}:
            raise ValueError('Unknown region; imported scenes need regional recovery via revise first')
        delivery_dir=s['delivery'].replace('\\','/')
        delivery=under(project,delivery_dir+'/delivery.json');receipt=read_json(delivery)
        delivered=under(project,delivery_dir+'/editable.pptx')
        source=under(project,run['candidate']['file'])
        if receipt['run_id']!=run['id'] or receipt['pptx_sha256']!=sha256(delivered) or sha256(source)!=sha256(delivered):
            raise WorkflowError('artifact_changed','Delivered baseline differs')
        number=s['run_seq']+1;rid=f'run-{number:04}';dest=project/'runs'/rid
        with staged_directory(dest) as stage:
            for relative in run['frozen']:
                target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(under(project,run['dir']+'/'+relative),target)
            write_json(stage/'frozen-inputs.json',run['frozen'])
            shutil.copyfile(source,stage/'candidate.pptx')
            shutil.copyfile(under(project,run['audit']['file']),stage/'audit.json')
        s.setdefault('old_runs',[]).append(copy.deepcopy(run));s['run_seq']=number
        s['run']={'id':rid,'dir':'runs/'+rid,'frozen':copy.deepcopy(run['frozen']),'reviews':{},'attempt':0,
                  'candidate':file_record(project,dest/'candidate.pptx'),'audit':file_record(project,dest/'audit.json'),
                  'revision_source':{'run_id':run['id'],'delivery':s['delivery'],'slide':args['slide'],'region':args['region']}}
        s['status']='ready_to_continue';s['failure']=None
        save(project,s,'revision_candidate_created',{'source_run':run['id'],'reason':args['reason']})
        return {**brief(s),'scene_sha256':sha256(dest/'scene.json'),'pptx_sha256':sha256(dest/'candidate.pptx'),
                'next_hint':'Use patch for the selected region, then compare and adopt. New reviews and delivery gates are required.'}


@scoped
def submit(project:Path,response_path:Path|dict,expected_revision=None,*,lock_held=False,adoption=None,return_next=False):
    require_capabilities('workflow.submit')
    if return_next:require_capabilities('workflow.next')
    with nullcontext() if lock_held else locked(project):
        s=load(project);t=s.get('active_task')
        if not t:raise WorkflowError('no_active_task','No active task. A previously accepted response cannot be submitted twice.')
        check_packet(project,s,t);response=response_path if isinstance(response_path,dict) else read_json(response_path);keys(response,['task_id','token','result'])
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision!=t['base_revision']):
            raise WorkflowError('stale_task','Submission revision does not match the current task')
        if response['task_id']!=t['id'] or response['token']!=t['token']:raise WorkflowError('stale_task','Task ID/token mismatch; call next and use the current template')
        if _managed_policy is not None:
            from toolbox_manager.contracts import validate_result
            validate_result(t['kind'],response['result'],ROOT)
            response={**response,'result':_managed_policy.result_paths(response['result'],t['kind'])}
        packet=read_json(under(project,t['packet']));working=copy.deepcopy(s)
        try:attachments=_accept_result(project,working,t,packet,response['result'])
        except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
            if getattr(exc,'code',None)=='permission_denied':raise
            # No state commit. Valid siblings and the issued task remain intact.
            raise WorkflowError('invalid_submission',str(exc),'Only correct result fields and resubmit the same current task; do not rewrite the full scene.')
        s=working;record={'task_id':t['id'],'kind':t['kind'],'target':t['target'],'base_revision':t['base_revision'],
                         'packet_sha256':t['packet_sha256'],'result':response['result'],'attachments':attachments,'accepted_at':now()}
        p=project/'workflow/results'/f'{t["id"]}.json'
        if p.exists():raise WorkflowError('record_collision','Accepted task record already exists')
        extra_records = []
        if t['kind'] == 'review_full':
            bundle = {row['region_id']: row for row in packet['context'].get('review_bundle', [])}
            for i, row in enumerate(response['result'].get('additional_reviews', []), 1):
                extra_path = p.with_name(f'{t["id"]}-local-{i:02}.json')
                if extra_path.exists():raise WorkflowError('record_collision','Additional review record already exists')
                info = bundle[row['region_id']]
                extra = {**record, 'kind': 'review_local', 'result': row['result'],
                         'target': {**t['target'], 'region_id': row['region_id'], 'key': info['key']},
                         'batched_with': t['id']}
                extra_records.append((extra_path, extra, info['key']))
        write_json(p,record);rec=file_record(project,p);s['accepted'].append(rec)
        for extra_path, extra, key in extra_records:
            write_json(extra_path, extra)
            extra_ref = file_record(project, extra_path)
            s['accepted'].append(extra_ref)
            s['run']['reviews'][key] = extra_ref
        for attachment in attachments:s['tracked_inputs'][attachment['file']]=attachment['sha256']
        kind=t['kind'];r=response['result']
        if kind=='source_review':_page(s,t['target']['slide_id'])['source_review']={**rec,'status':r['status']}
        if kind in {'review_full','review_local','editable_behavior','reproducibility'}:s['run']['reviews'][t['target']['key']]=rec
        if kind in {'preview_full','preview_local'}:
            s['run']['preview']['reviews'][t['target']['key']]=rec
            s['run']['preview']['status']='review_in_progress'
        failed=(kind in {'source_review','review_local','preview_local','editable_behavior','reproducibility'} and r['status']!='passed' or
                kind in {'review_full','preview_full'} and any(c['status']!='passed' for c in r['checks'].values()))
        if kind == 'review_full' and any(row['result']['status'] != 'passed' for row in r.get('additional_reviews', [])):
            failed = True
        if kind in {'preview_full','preview_local'}:
            if failed:s['run']['preview']['status']='needs_attention'
            elif not _preview_queue(project,s):s['run']['preview']['status']='review_completed'
        s['active_task']=None;s['status']='awaiting_revision' if failed else 'ready_to_continue'
        if adoption is not None:
            operation_id, marker = adoption
            s.setdefault('local_adoptions', {})[operation_id] = marker
        save(project,s,'task_accepted',{'id':t['id'],'kind':kind})
        result = {**brief(s),'accepted_task':t['id'],
                  'submission':{'state':'accepted','task_id':t['id'],'record':rec,'replay_allowed':False},
                  'next_step':{'state':'needs_revision' if failed else 'not_requested'},
                  'next_command':['next','--project',str(project.resolve())]}
        if return_next and not failed:
            # Submission is committed. A subsequent failure must never invite replay.
            try:
                _progress(project,s)
                selected,status=_choose(project,s)
                if selected:
                    s['status']=status;_issue(project,s,*selected)
                result.update(_public_task(project,s))
                if s.get('failure') or s.get('operation'):
                    result['next_error']=copy.deepcopy(s.get('failure') or {
                        'code':'interrupted_operation','message':'Inspect the current operation before recovery'})
                    result['next_error']['hint']='Submission accepted; inspect status. Do not resubmit.'
                    result['next_step']={'state':'failed','resume_with':'rebuild_status'}
                else:
                    result['next_step']={'state':'issued' if s.get('active_task') else 'waiting',
                                         'task_id':(s.get('active_task') or {}).get('id')}
            except Exception as exc:
                result['next_error']={'code':getattr(exc,'code','next_failed'),'message':str(exc),
                                      'hint':'Submission accepted; inspect status. Do not resubmit.'}
                result['next_step']={'state':'failed','resume_with':'rebuild_status'}
        return result


def retry(project:Path,reason:str):
    with locked(project):
        s=load(project);text(reason,'retry reason')
        if not s.get('failure') and not s.get('operation'):raise WorkflowError('not_failed','No failed/interrupted operation. Do not restart successful work; use next or revise.')
        _cancel(s,'retry');s['failure']=None;s['operation']=None;s['status']='ready_to_continue'
        save(project,s,'explicit_retry',{'reason':reason});return brief(s)


def revise(project:Path,slide_id:str,region_id:str|None,reason:str):
    require_capabilities('workflow.revise')
    with locked(project):
        s=load(project);p=_page(s,slide_id);text(reason,'revision reason')
        if p.get('imported_slide') is not None:
            if region_id:
                from workflow_recovery import context
                if not s.get('run'):
                    raise WorkflowError('recovery_blocked','Imported regional revision needs a current paired run')
                # Validate every recovered context before the one atomic state commit.
                restored=[(page,context(project,s,page,page['imported_slide']))
                          for page in s['pages'] if page.get('imported_slide') is not None]
                selected=next(c for page,c in restored if page['id']==slide_id)
                if region_id not in {r['id'] for r in selected['plan']['regions']}:raise ValueError('Unknown region')
                for page,c in restored:page.update(c)
                _cancel(s,reason);p['source_review']=None
                s['run']['reviews']={}
                for key in ('review','gate'):s['run'].pop(key,None)
                s['status']='ready_to_continue'
                save(project,s,'imported_region_reopened',{'slide_id':slide_id,'region_id':region_id,'reason':reason})
                return brief(s)
            from evidence_contract import review_mapping
            p['mapping']=review_mapping({'canvas':s['canvas']},p['imported_slide'],p['size'])
            p['previous_imported_slide']=p.pop('imported_slide')
            p['planning_state']='awaiting_replanning'
        if region_id:
            if not p.get('plan') or region_id not in {r['id'] for r in p['plan']['regions']}:raise ValueError('Unknown region')
            from workflow_evidence import capture_revision_feedback
            region=next(r for r in p['plan']['regions'] if r['id']==region_id)
            p.setdefault('revision_feedback',{})[region_id]=capture_revision_feedback(project,s,p,region,reason)
            if region_id in p['fragments']:p.setdefault('previous_fragments',{})[region_id]=p['fragments'].pop(region_id)['raw']
            for job in s['asset_jobs']:
                if job['slide_id']==slide_id and job['region_id']==region_id and job['status']!='completed':job['status']='cancelled'
        else:
            from element_scope import compiled_scope
            scope=compiled_scope(p) or p.get('previous_imported_slide',{}).get('element_scope')
            if scope is not None:
                p['previous_element_scope']={k:v for k,v in scope.items() if k!='bindings'}
            p['plan']=None;p['fragments']={};p['previous_fragments']={}
            p.pop('revision_feedback',None)
            p.pop('review_plan',None)
            for job in s['asset_jobs']:
                if job['slide_id']==slide_id and job['status']!='completed':job['status']='cancelled'
        p['source_review']=None;_invalidate_run(s,reason);save(project,s,'region_reopened',{'slide_id':slide_id,'region_id':region_id,'reason':reason})
        return brief(s)


def _invalidate_run(s,reason):
    _cancel(s,reason)
    if s.get('run'):s.setdefault('old_runs',[]).append(s['run'])
    s['run']=None;s['failure']=None;s['operation']=None;s['status']='awaiting_analysis'
    s.pop('pending_candidate',None)


def replace_candidate(project:Path,pptx:Path,reason:str):
    with locked(project):
        s=load(project);text(reason,'reason')
        if not _all_source_passed(s):raise WorkflowError('source_not_reviewed','Complete source checks before replacing a candidate')
        if pptx.suffix.lower()!='.pptx':raise ValueError('Candidate must be .pptx')
        rel=import_file(pptx,project,'input/candidates');s['tracked_inputs'][rel]=sha256(project/rel)
        _invalidate_run(s,reason);s['builder']='external';s['pending_candidate']=file_record(project,project/rel)
        save(project,s,'candidate_replaced',{'file':rel,'reason':reason});return brief(s)


def replace_scene(project:Path,scene_path:Path,reason:str):
    require_capabilities('pptx.validate')
    with locked(project):
        s=load(project);text(reason,'reason')
        # References must remain byte-identical; changes are a new task/project, not a hidden edit.
        incoming=read_json(scene_path);old_refs=[p['sha256'] for p in s['pages']]
        if len(incoming.get('slides',[]))!=len(old_refs):raise ValueError('Replacement must keep page count and reference identity')
        for index,slide in enumerate(incoming['slides']):
            if sha256(resolve_asset(scene_path.parent,slide['reference']))!=old_refs[index]:raise ValueError('Replacement reference differs; start a new project')
        if [p['id'] for p in s['pages']]!=[p['id'] for p in incoming['slides']]:raise ValueError('Replacement must keep stable page IDs')
        from element_scope import compiled_scope
        for page, slide in zip(s['pages'], incoming['slides']):
            old_scope=compiled_scope(page)
            if old_scope is not None and slide.get('element_scope') != old_scope:
                raise ValueError('element_scope: replacement must retain scope and bindings; revise the page to change decisions')
        # Import in a task-owned temporary project, then copy only new assets and rewrite references.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='ppt-scene-check-') as temp:
            temp=Path(temp);canvas,title,pages=import_scene(scene_path,temp)
            for old,new in zip(s['pages'],pages):
                new['native_first']=old.get('native_first',False)
                new['reference']=old['reference'];new['imported_slide']['reference']=old['reference']
                from workflow_recovery import context, review_context
                try:
                    if canvas!=s['canvas']:raise WorkflowError('replanning_required','Canvas changed')
                    new.update(review_context(project,s,old,new['imported_slide']))
                    new.update(context(project,s,old,new['imported_slide']))
                except WorkflowError as exc:
                    if exc.code!='replanning_required':raise
                    new['planning_state']='invalid'
                    new['planning_reason']=str(exc)
                for o in walk_objects(new['imported_slide']['objects']):
                    if o['kind']=='image':
                        rel=import_file(temp/o['asset'],project);o['asset']=rel;s['tracked_inputs'][rel]=sha256(project/rel)
                for unit in new['imported_slide'].get('element_scope',{}).get('units',[]):
                    if 'source' in unit:
                        rel=import_file(temp/unit['source']['asset'],project)
                        unit['source']['asset']=rel;s['tracked_inputs'][rel]=sha256(project/rel)
            _invalidate_run(s,reason);s.update(canvas=canvas,title=title,pages=pages)
        save(project,s,'scene_replaced',{'reason':reason});return brief(s)


@scoped
def complete(project:Path):
    require_capabilities('workflow.finish')
    from project_journal import requirement
    needed = requirement(project, finishing=True)
    if needed:
        return {**brief(load(project)), 'checkpoint_required': needed}
    with locked(project):
        s=load(project);_progress(project,s)
        if s['status']=='delivered':
            saved=s['delivery'].replace('\\','/')+'/editable.pptx'
            return {**brief(s),'delivery_created':False,
                    'delivery':str(under(project,saved).parent),
                    'next_hint':'Delivery already recorded. Inspect the existing delivery; no files were rewritten.',
                    'note':'Existing delivery is preserved; no overwrite.'}
        if s['status']!='ready_to_deliver':
            result={**brief(s),'delivery_created':False,
                    'delivery_block_reason':'Required production or review steps remain. pages_ready counts pages with reconstructed content, not accepted PPT pages.'}
            if s['status']=='awaiting_revision':
                result['next_hint']='Delivery not created. Call revise for the failed slide/region, then next. Do not repeat finish.'
            elif not s.get('operation') and not s.get('failure'):
                result['next_hint']='Delivery not created. Call next to build/render or receive the pending task; submit actual review evidence. Do not repeat finish.'
            return result
        require_capabilities('delivery.verify')
        run=s['run'];base=under(project,run['dir']+'/scene.json').parent
        # Re-evaluate the entire evidence chain at the final boundary, not only stored status.
        from verify_delivery import verify
        result=verify(under(project,run['candidate']['file']),under(project,run['audit']['file']),under(project,run['render']['file']),
                      under(project,run['review']['file']),under(project,run['comparison']['file']),base/'scene.json')
        if result['status']!='passed':raise WorkflowError('delivery_gate_changed','Current evidence no longer passes: '+json.dumps(result,ensure_ascii=False))
        dest=project/'delivery'/run['id']
        if dest.exists():
            return {**brief(s),'delivery_created':False,'delivery':str(dest),'note':'Existing delivery is preserved; no overwrite.'}
        with staged_directory(dest) as stage:
            shutil.copyfile(under(project,run['candidate']['file']),stage/'editable.pptx')
            shutil.copytree(base,stage/'production')
            (stage/'README.md').write_text('# 交付\n\neditable.pptx与production中当前候选字节一致。预览和对照在production对应目录。\n验收只覆盖报告声明项目；Agent看图及修改测试属于其提交的记录，收据本身不能证明判断正确。\n',encoding='utf-8')
            write_json(stage/'delivery.json',{'status':'passed','pptx_sha256':sha256(stage/'editable.pptx'),'run_id':run['id'],'gate':result})
        s['status']='delivered';s['delivery']=dest.relative_to(project).as_posix();save(project,s,'delivery_created',{'dir':s['delivery']})
        return {**brief(s),'delivery_created':True,'delivery':str(dest)}


def review_again(project:Path,task_id:str,reason:str):
    """Reopen an assertion, not rebuild a successful file; old statements remain archived."""
    with locked(project):
        s=load(project);text(reason,'reason');record=None
        for ref in s['accepted']:
            data=read_json(under(project,ref['file']))
            if data['task_id']==task_id:record=data;break
        if not record:raise WorkflowError('unknown_review','No accepted task with this ID')
        kind=record['kind'];target=record['target']
        if kind=='source_review':_page(s,target['slide_id'])['source_review']=None
        elif kind in {'review_full','review_local','editable_behavior','reproducibility'}:
            if not s.get('run') or target['key'] not in s['run']['reviews']:
                raise WorkflowError('old_run_review','That review is not active in the current run')
            current=read_json(under(project,s['run']['reviews'][target['key']]['file']))
            if current['task_id']!=task_id:raise WorkflowError('old_review','A newer review already replaced this task')
            s['run']['reviews'].pop(target['key'])
        elif kind in {'preview_full','preview_local'}:
            pre=(s.get('run') or {}).get('preview')
            if not pre or target['key'] not in pre['reviews']:raise WorkflowError('old_run_review','Preview is not in the current run')
            current=read_json(under(project,pre['reviews'][target['key']]['file']))
            if current['task_id']!=task_id:raise WorkflowError('old_review','A newer preview review replaced this task')
            pre['reviews'].pop(target['key']);pre['status']='awaiting_review'
        else:raise WorkflowError('not_review','Only review tasks can be reopened this way')
        if s.get('run'):
            s['run'].pop('gate',None);s['run'].pop('review',None)
        _cancel(s,reason);s['status']='ready_to_continue'
        save(project,s,'review_reopened',{'task_id':task_id,'reason':reason});return brief(s)
