"""Lossless current-task delivery and local text accounting. No host token estimates."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from .storage import digest
DETAIL_BYTES=32*1024*1024


def text_size(value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return {'json_chars': len(text), 'json_utf8_bytes': len(text.encode('utf-8'))}


def compact_task(task, packet, template):
    # Retain every context field, including future task-specific constraints.
    # Only duplicate tool descriptors are shortened. Packets stay immutable.
    task['context'] = copy.deepcopy(packet['context'])
    task['response'] = copy.deepcopy(template)
    task['response_detail'] = 'compact'
    task['delivery_format'] = 'ppt-task-inline/2'
    task['required_read_files'] = []
    task['contract_query'] = {'tool':'toolbox_project_inspect','action':'contract',
                              'when':'Only if current template/constraints are insufficient; use the current project.'}
    task['source_files'] = [{'file': str(path), 'sha256': digest(path.read_bytes())}
                            for path in (Path(task['packet']), Path(task['response_template']))]
    # Losslessly expose protocol/extension fields omitted by the historical envelope.
    represented = {'task_id','token','kind','target','base_revision','instructions',
                   'context','required_view_files','references','suggested_tools','input_files'}
    task['packet_metadata'] = {k: copy.deepcopy(v) for k,v in packet.items() if k not in represented}
    task['read_instruction'] = ('Current context and response template are complete inline. No packet/template reread is required. '
        'Open must_view_files and any task-specific manuals actually needed; source_files are immutable provenance, not viewing evidence. '
        'If delivery_format is unknown or data is missing, request response_detail=full.')
    return task


def measure_delivery(result):
    """Count only the exact JSON body before adding this accounting record."""
    measured = text_size({k:v for k,v in result.items() if k!='delivery_metrics'})
    task = result.get('task') or {}
    measured['task'] = text_size(task)
    measured['required_text_file_bytes'] = sum(Path(row['file']).stat().st_size
        for row in task.get('required_read_files', []))
    measured['scope'] = ('Local compact JSON serialization, excluding this record; not wire bytes, model tokens, '
                          'image traffic, or unobserved manual reads.')
    result['delivery_metrics'] = measured
    measured['total_scope']='Exact compact JSON serialization including this accounting record.'
    # Include the accounting record itself. Iterate until the decimal digit count stabilizes.
    measured['total_json_utf8_bytes']=0
    for _ in range(8):
        total=text_size(result)['json_utf8_bytes']
        if measured['total_json_utf8_bytes']==total:break
        measured['total_json_utf8_bytes']=total
    return result


def compact_response(manager, full, project, command, output_dir, record):
    """Persist complete facts, then project known duplicate/detail fields only."""
    import os
    import re
    project=Path(project).resolve();output_dir=Path(output_dir).resolve()
    cid=full.get('call_id') or record.get('call_id')
    if (not isinstance(cid,str) or not re.fullmatch(r'[0-9a-f]{32}',cid)
            or output_dir!=project/'logs'/'tool-calls'/cid):
        # Calls denied before initialization may have manager-cache logs. Never invent a project query.
        result=copy.deepcopy(full);result['response_detail']='full'
        result['compact_fallback']='project_response_archive_unavailable'
        return measure_delivery(result)
    payload={'format':'ppt-response-detail/1','call_id':cid,'command':command,
             'project':str(project),'project_id':record.get('project_id'),
             'result':copy.deepcopy(full)}
    data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(data)>DETAIL_BYTES:
        result=copy.deepcopy(full);result['response_detail']='full'
        result['compact_fallback']='response_archive_exceeds_inspection_limit'
        return measure_delivery(result)
    path=output_dir/'response-full.json'
    # Same-volume atomic publication; task-owned temporary file is always removed.
    scratch=(project/'.tmp'/'codex'/'response-delivery'/cid).resolve()
    if not scratch.is_relative_to(project):raise ValueError('Response archive scratch leaves current project')
    parent_existed=scratch.parent.exists()
    scratch.mkdir(parents=True,exist_ok=False)
    temporary=scratch/'response.json'
    try:
        temporary.write_bytes(data);os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
        scratch.rmdir()
        if not parent_existed:
            try:scratch.parent.rmdir()
            except OSError:pass  # Another concurrent call may own a sibling.
    h=digest(data);record['response_detail']={'format':payload['format'],'file':'response-full.json','sha256':h}
    result=copy.deepcopy(full);result.pop('stdout',None);result.pop('stderr',None)
    result['delivery_format']='ppt-workflow-response/3';result['response_detail']='compact'
    result['detail_reference']={'format':payload['format'],'sha256':h,
       'file':path.relative_to(project).as_posix(),
       'query':{'tool':'toolbox_project_inspect','project':str(project),'action':'response','call_id':cid}}
    omitted=[]
    def project_fields(key, names):
        row=result.get(key)
        if not isinstance(row,dict):return
        for name in names:
            if name in row:
                row.pop(name);omitted.append('/result/'+key+'/'+name)
    # Identity/current state and effective values survive. Definitions, prose and history are queryable.
    project_fields('production_settings',['definitions','instructions','global_values','available_regions'])
    task=result.get('task')
    idle_finish=command=='finish' and not task and not result.get('active_task')
    if idle_finish:
        project_fields('project_context',['paths'])
        project_fields('validation_metrics',['seconds','timing_note'])
        if 'timings' in result:
            result.pop('timings');omitted.append('/result/timings')
        # No material authoring task remains. Keep actual authorization and drawing mode,
        # while moving the static routing manual and repeated settings to complete facts.
        material=result.get('material_policy')
        original_production=full.get('production_settings')
        if isinstance(material,dict):
            if material.get('production_settings')==original_production and 'production_settings' in material:
                material['production_settings']={'inline_reference':'/production_settings'}
            if 'plan_update' in material:
                material.pop('plan_update');omitted.append('/result/material_policy/plan_update')
            route=material.get('illustration_route')
            if isinstance(route,dict):
                static=['instruction','work_graph','category_defaults','legacy_fallback','assessor','record']
                if any(k in route for k in static):
                    for key in static:route.pop(key,None)
                    omitted.append('/result/material_policy/illustration_route')
        applied=(result.get('production_settings') or {}).get('applied')
        if (isinstance(applied,dict) and isinstance(original_production,dict)
                and 'instructions' in applied and applied['instructions']==original_production.get('instructions')):
            applied.pop('instructions');omitted.append('/result/production_settings/applied/instructions')
    project_fields('project_context',['directory_contract','references','initialization'])
    for key in ['production_settings','material_policy']:
        if isinstance(result.get('project_context'),dict) and key in result['project_context']:
            result['project_context'].pop(key);omitted.append('/result/project_context/'+key)
    project_fields('stage_context',['stages','step_types','recommendations','instructions'])
    stage=result.get('stage_context') or {}
    assistance=stage.get('assistance_packet')
    if isinstance(assistance,dict) and assistance.get('phase')==stage.get('phase'):
        assistance['phase']={'inline_reference':'/stage_context/phase'}
    if idle_finish and isinstance(assistance,dict) and isinstance(assistance.get('evidence_ids'),list):
        assistance['evidence_count']=len(assistance.pop('evidence_ids'))
        omitted.append('/result/stage_context/assistance_packet/evidence_ids')
    if isinstance(result.get('edit_summary'),dict):
        row=result['edit_summary'];tests=row.get('tests',[]);limits=row.get('limitations',[])
        for key in ['tests','actions','limitations','legacy_note','note','stored_evidence']:
            if key in row:row.pop(key);omitted.append('/result/edit_summary/'+key)
        row.update(test_count=len(tests),limitation_count=len(limits),
                   status_counts={status:sum(t.get('status')==status for t in tests)
                                  for status in sorted({t.get('status','unknown') for t in tests})})
        row['unresolved_checks']=[{k:v for k,v in limit.items() if k in {
            'object_id','slide_id','operation','scope','status','tested_value','finding','required_adjustment'}}
            for limit in limits]
    if isinstance(result.get('post_delivery'),dict) and 'project' in result['post_delivery']:
        if result['post_delivery']['project']==result.get('workbench_project'):
            result['post_delivery']['project']={'inline_reference':'/workbench_project'}
    if task:
        packet=json.loads(Path(task['packet']).read_text(encoding='utf-8'))
        template=json.loads(Path(task['response_template']).read_text(encoding='utf-8'))
        compact_task(task,packet,template)
        task['submission_draft_query']={'tool':'toolbox_project_inspect','project':str(project),
            'action':'submission','when':'Optional pinned request scaffold, action choices and independent local review drafts.'}
        task['related_tools']=[{'id':row['id'],'title':row.get('title',row['id']),
                               'describe_tool':'toolbox_describe'} for row in task.get('related_tools',[])]
        if task.get('contract_summary',{}).get('constraints')==task.get('context',{}).get('submission_constraints'):
            task['contract_summary']['constraints']={'inline_reference':'/task/context/submission_constraints'}
    result['detail_reference']['omitted_pointers']=omitted
    if idle_finish:
        result['compact_size_target_bytes']=10240
    measure_delivery(result)
    if idle_finish and result['delivery_metrics']['total_json_utf8_bytes']>10240:
        result['compact_size_target_exceeded']=True
        result['compact_size_note']='Necessary outcomes and warnings retained; read detail_reference for full facts.'
        measure_delivery(result)
    return result


def production_context(manager, full):
    """Public default. Unknown/customized bootstrap text falls back to full context."""
    manifest = manager.root/'assets/context-bootstrap.json'
    if not manifest.is_file():
        return {**full, 'context_profile': 'full', 'profile_fallback': 'bootstrap_manifest_missing'}
    reviewed = json.loads(manifest.read_text(encoding='utf-8'))
    documents = []
    for path, expected in reviewed['sources'].items():
        doc = manager.document(path)
        if doc['customized'] or doc['base_sha256'] != expected:
            return {**full, 'context_profile': 'full', 'profile_fallback': 'bootstrap_changed_or_customized'}
        documents.append({'path':path,'sha256':doc['base_sha256'],'revision':doc['revision'],
                          'tool':'toolbox_manual'})
    result = dict(full)
    # The full current skill, effective policies, instructions, identity, disabled
    # tools and learning consent survive. Only reviewed duplicate startup prose goes.
    result.pop('startup_prompt', None)
    result['context_profile'] = 'production'
    result['bootstrap_documents'] = documents
    result['workflow_defaults'] = {'response_detail':'compact','return_next':True,
        'instruction':'Bind the project, then read current status. Use current inline task context and actual required images. '
                      'Do not replay accepted or unknown submissions. Full context remains available with profile=full.'}
    return measure_delivery(result)
