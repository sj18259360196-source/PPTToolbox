"""Hash-bound sampled edit evidence. An index never supplies a test verdict."""
from pathlib import Path
if __package__:
    from .common import read_json, sha256
    from .workflow_store import under
else:
    from common import read_json, sha256
    from workflow_store import under

TEXT = {'type':'string','minLength':1}
REF = {'type':'object','additionalProperties':False,'required':['file','sha256'],
       'properties':{'file':TEXT,'sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'}}}
SCHEMA = {'type':'object','additionalProperties':False,
 'required':['format','project_id','run_id','candidate_sha256','entries'],
 'properties':{'format':{'const':'edit-evidence-index/1'},'project_id':TEXT,'run_id':TEXT,
 'candidate_sha256':REF['properties']['sha256'], 'entries':{'type':'array','minItems':1,'items':{
 'type':'object','additionalProperties':False,
 'required':['id','test_case_id','slide','object_id','action','check','receipt','input','output','supersedes','reason'],
 'properties':{'id':TEXT,'test_case_id':TEXT,'slide':{'type':'integer','minimum':1},'object_id':TEXT,'action':TEXT,
 'check':{'enum':['content_readback','longer_text_layout']},'receipt':REF,'input':REF,'output':REF,
 'derived_from':TEXT,'supersedes':{'type':'array','uniqueItems':True,'items':TEXT},
 'reason':TEXT}}}}}

def bound(project, ref):
    p=under(Path(project),ref['file'])
    if not p.is_file() or sha256(p)!=ref['sha256']:
        raise ValueError('Edit evidence file missing or hash changed: '+ref['file'])
    return p

def resolve(project, state, reference, attached=()):
    import jsonschema
    jsonschema.validate(reference,REF)
    index=read_json(bound(project,reference));jsonschema.validate(index,SCHEMA)
    candidate=under(Path(project),state['run']['candidate']['file'])
    if (index['project_id']!=state['project_id'] or index['run_id']!=state['run']['id']
            or index['candidate_sha256']!=sha256(candidate)):
        raise ValueError('Edit evidence index belongs to another project, run or candidate')
    if state['run']['candidate'].get('sha256', index['candidate_sha256']) != index['candidate_sha256']:
        raise ValueError('Current candidate file differs from the recorded candidate')
    entries={};receipts=set();files={bound(project,reference)}
    for e in index['entries']:
        if e['id'] in entries:raise ValueError('Duplicate edit evidence ID')
        rp=bound(project,e['receipt']);ip=bound(project,e['input']);op=bound(project,e['output'])
        r=read_json(rp);receipts.add(rp);files.update([rp,ip,op])
        if r.get('format')!='ppt-edit-readback/1':raise ValueError('Unknown edit receipt format')
        if r.get('source_sha256')!=e['input']['sha256'] or r.get('edited_sha256')!=e['output']['sha256']:
            raise ValueError('Edit receipt does not bind input/output hashes')
        if Path(r.get('source','')).resolve()!=ip or (rp.parent/r.get('edited_file','')).resolve()!=op:
            raise ValueError('Edit receipt does not bind actual input/output files')
        for render in r.get('renders',[]):
            renderpath=(rp.parent/render['file']).resolve()
            if not renderpath.is_relative_to(Path(project).resolve()) or not renderpath.is_file() or sha256(renderpath)!=render['sha256']:
                raise ValueError('Edit render is missing, escaped or changed')
            files.add(renderpath)
        matches=[c for c in r.get('checks',[]) if c.get('operation',{}).get('name')==e['object_id']
                 and c.get('operation',{}).get('slide')==e['slide']
                 and c.get('operation',{}).get('op')==e['action']]
        if len(matches)!=1:raise ValueError('Edit receipt target/action is missing or ambiguous')
        c=matches[0]
        success=(r.get('status')=='passed' and c.get('matches') is True)
        if 'font_size_pt' in c.get('operation',{}):
            success=success and c.get('font_size_matches') is True
        if e['check']=='longer_text_layout':success=success and c.get('longer_text_layout',{}).get('status')=='within_frame'
        entries[e['id']]={'entry':e,'passed':success,'check':c}
    def identity(e):return tuple(e[k] for k in ['test_case_id','slide','object_id','action','check'])
    def visit(ident, stack):
        if ident in stack:raise ValueError('Cyclic edit evidence relation')
        e=entries[ident]['entry'];parents=list(e['supersedes'])+([e['derived_from']] if e.get('derived_from') else [])
        for parent in parents:
            if parent not in entries:raise ValueError('Broken edit evidence relation')
            visit(parent,stack|{ident})
        if e.get('derived_from'):
            prior=entries[e['derived_from']]['entry']
            if prior['output']['sha256']!=e['input']['sha256']:raise ValueError('Broken derived input chain')
            if (prior['slide'],prior['object_id'])!=(e['slide'],e['object_id']):raise ValueError('Cross-object derived input')
        elif e['input']['sha256']!=index['candidate_sha256']:
            raise ValueError('Input is not derived from the candidate')
        for parent in e['supersedes']:
            if identity(entries[parent]['entry'])!=identity(e):raise ValueError('Cross-case/object/check replacement')
            # A shorter replacement sentence cannot clear the original long-text case.
            # A recorded font adjustment is an explicit condition on the new verdict.
            prior_op={k:v for k,v in entries[parent]['check']['operation'].items() if k!='font_size_pt'}
            current_op={k:v for k,v in entries[ident]['check']['operation'].items() if k!='font_size_pt'}
            if prior_op!=current_op:raise ValueError('Replacement changes the tested operation or content')
            if not entries[ident]['passed']:raise ValueError('Failed evidence cannot supersede a check')
    for ident in entries:visit(ident,set())
    replaced={p for v in entries.values() for p in v['entry']['supersedes']}
    unresolved=[i for i,v in entries.items() if i not in replaced and not v['passed']]
    if unresolved:raise ValueError('Unresolved indexed edit checks: '+', '.join(unresolved))
    # Search registered project evidence too: omission of a failure is not resolution.
    candidates=set(Path(p).resolve() for p in attached if Path(p).suffix.lower()=='.json')
    explicit=set(candidates)
    candidates.update(receipts)
    input_hashes={index['candidate_sha256']}|{v['entry']['input']['sha256'] for v in entries.values()}
    for file, digest in state.get('tracked_inputs',{}).items():
        p=under(Path(project),file)
        if p.suffix.lower()=='.json':
            if sha256(p)!=digest:raise ValueError('Registered edit evidence changed: '+file)
            candidates.add(p)
    for p in candidates:
        if not p.is_file() or p.stat().st_size>4_000_000:continue
        try:r=read_json(p)
        except (ValueError,UnicodeError):continue
        if isinstance(r,dict) and r.get('format')=='ppt-edit-readback/1' and r.get('longer_text_layout')=='overflow_detected':
            if p.resolve() not in explicit and r.get('source_sha256') not in input_hashes:continue
            if p.resolve() not in receipts:raise ValueError('Unregistered historical overflow receipt: '+str(p))
            if not any(c.get('longer_text_layout',{}).get('status')=='overflow_detected' for c in r.get('checks',[])):
                raise ValueError('Historical overflow receipt lacks the failed check details')
            for c in r.get('checks',[]):
                if c.get('longer_text_layout',{}).get('status')=='overflow_detected':
                    covered=[i for i,v in entries.items() if bound(project,v['entry']['receipt'])==p.resolve()
                             and v['entry']['slide']==c['operation'].get('slide')
                             and v['entry']['object_id']==c['operation']['name'] and v['entry']['action']==c['operation']['op']
                             and v['entry']['check']=='longer_text_layout']
                    if not covered or any(i not in replaced for i in covered):raise ValueError('Historical overflow check remains unresolved')
    return {'format':'edit-evidence-resolution/1','effective_ids':[i for i in entries if i not in replaced],
            'historical_ids':sorted(replaced),'files':sorted(map(str,files)),
            'effective_checks':[{'id':i,'test_case_id':v['entry']['test_case_id'],
              'slide':v['entry']['slide'],'object_id':v['entry']['object_id'],'action':v['entry']['action'],'check':v['entry']['check'],
              'input_sha256':v['entry']['input']['sha256'],'output_sha256':v['entry']['output']['sha256'],
              'operation':v['check']['operation'],'visual_status':'not_certified_by_index'}
              for i,v in entries.items() if i not in replaced]}
