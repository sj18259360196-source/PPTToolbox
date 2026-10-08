"""Task-specific cross-model runner with explicit network/upload approval.
Offline replay, live API micro-tasks, and imported full-workflow evidence are separate tracks.
The runner never executes model-authored code and never fills production reviews as passed.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import random
import statistics
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from common import read_json,write_json,sha256,staged_directory
from benchmark_suite import make_suite,load_suite,public_packet,grade


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError('Model endpoint redirected; configure and approve the exact final endpoint first')


def fingerprint():
    result={'os':platform.system(),'python':platform.python_version()}
    for lib in ['python-pptx','Pillow','numpy','lxml']:
        try:result[lib]=importlib.metadata.version(lib)
        except importlib.metadata.PackageNotFoundError:result[lib]=None
    return result


def parse_model_json(value):
    if not isinstance(value,str):raise ValueError('Text output must be a string')
    value=value.strip()
    if value.startswith('```'):
        lines=value.splitlines()
        if lines[-1].strip()!='```':raise ValueError('Unclosed response fence')
        value='\n'.join(lines[1:-1])
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate response key: '+k)
            out[k]=v
        return out
    result=json.loads(value,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    if not isinstance(result,dict):raise ValueError('Model must return one JSON object')
    return result


def validated_config(config,suite):
    if not isinstance(config,dict) or set(config)-{'models','repetitions','max_requests','max_output_tokens','timeout_seconds','max_repair_attempts','schedule_seed'}:raise ValueError('Unknown benchmark configuration fields')
    models=config.get('models',[])
    if not isinstance(models,list) or not models:raise ValueError('At least one explicitly configured model is required')
    if len(models)>12:raise ValueError('At most 12 model entries per run')
    ids=[]
    for m in models:
        allowed={'id','model','base_url','api_kind','api_key_env','parameters','allow_local_http','allow_no_auth','token_limit_field'}
        if not isinstance(m,dict) or set(m)-allowed or not {'id','model','base_url','api_kind'}<=m.keys():raise ValueError('Model entry requires id/model/base_url/api_kind; keys must be supplied through env only')
        if not isinstance(m['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}',m['id']):raise ValueError('Safe unique model ID required')
        if not isinstance(m['model'],str) or not m['model'].strip() or m['model'].startswith('REPLACE_'):raise ValueError('Provide the actual model ID, not a placeholder')
        u=urlparse(m['base_url'])
        loopback=u.hostname in {'127.0.0.1','localhost','::1'}
        if not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('base_url must not contain credentials, query or fragment')
        if u.scheme!='https' and not (u.scheme=='http' and loopback and m.get('allow_local_http')is True):raise ValueError('HTTPS required except explicitly approved local HTTP')
        if m['api_kind'] not in {'responses','chat_completions'}:raise ValueError('Only configured Responses or Chat Completions protocol is implemented')
        env=m.get('api_key_env')
        if env is not None and (not isinstance(env,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env)):raise ValueError('api_key_env must be an environment variable name, never a credential value')
        if not env and not (loopback and m.get('allow_no_auth')is True):raise ValueError('api_key_env required unless explicitly unauthenticated loopback')
        params=m.get('parameters',{})
        if not isinstance(params,dict) or set(params)-{'temperature','top_p','seed','reasoning_effort'}:raise ValueError('Only explicit sampling/reasoning parameters allowed; no arbitrary tool or input override')
        if any(isinstance(v,float) and not math.isfinite(v) for v in params.values()):raise ValueError('Finite model parameter required')
        if m.get('token_limit_field') not in ({None,'max_output_tokens'} if m['api_kind']=='responses' else {None,'max_tokens','max_completion_tokens'}):raise ValueError('token_limit_field must match the selected protocol')
        ids.append(m['id'])
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate model configuration IDs')
    # Same reported model may still appear under different endpoints; reports do not call that independent identity.
    repeat=config.get('repetitions',3);cap=config.get('max_requests',24);repair=config.get('max_repair_attempts',0)
    tokens=config.get('max_output_tokens',4096);timeout=config.get('timeout_seconds',120);schedule_seed=config.get('schedule_seed',1729)
    for v,label,lo,hi in [(repeat,'repetitions',1,30),(cap,'max_requests',1,1000),(repair,'max_repair_attempts',0,2),(tokens,'max_output_tokens',128,32768),(timeout,'timeout_seconds',1,300),(schedule_seed,'schedule_seed',0,4294967295)]:
        if type(v)is not int or not lo<=v<=hi:raise ValueError(f'{label} must be integer {lo}..{hi}')
    trials=len(models)*len(suite['cases'])*repeat;maxcalls=trials*(repair+1)
    if maxcalls>cap:raise ValueError(f'Plan needs at most {maxcalls} calls, above explicit cap {cap}; change the approved plan, never silently skip cases')
    return {'models':models,'repetitions':repeat,'max_requests':cap,'max_repair_attempts':repair,'max_output_tokens':tokens,'timeout_seconds':timeout,'schedule_seed':schedule_seed,'planned_trials':trials,'planned_max_calls':maxcalls,'max_requested_output_tokens':maxcalls*tokens}


def plan(suite_path,config_path):
    suite=load_suite(suite_path);conf=validated_config(read_json(config_path),suite)
    return {'status':'plan_only','track':'live_api_microtasks','suite_id':suite['id'],'suite_sha256':sha256(suite_path),'configuration_sha256':sha256(config_path),
            'models':[{'id':m['id'],'requested_model':m['model'],'endpoint':m['base_url'],'api_kind':m['api_kind'],'credential_present':bool(os.environ.get(m.get('api_key_env',''))) if m.get('api_key_env') else None} for m in conf['models']],
            'repetitions':conf['repetitions'],'schedule_seed':conf['schedule_seed'],'case_count':len(suite['cases']),'planned_trials':conf['planned_trials'],'planned_max_calls':conf['planned_max_calls'],'max_requested_output_tokens':conf['max_requested_output_tokens'],
            'network_calls':0,'scope':'No request sent. Numeric cap is not a monetary estimate; pricing belongs to the selected provider.'}


def request_payload(model,packet,limit,repair_text=None):
    public={k:v for k,v in packet.items() if k!='images'}
    prompt=json.dumps(public,ensure_ascii=False)
    if repair_text:prompt+='\nYour previous JSON/contract failed validation. Correct only that issue: '+repair_text
    image_data=[]
    for row in packet['images']:
        p=Path(row['file'])
        if p.stat().st_size>12*1024*1024:raise ValueError('Image exceeds per-file upload cap')
        if sha256(p)!=row['sha256']:raise ValueError('Benchmark input changed before upload')
        data='data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode('ascii');image_data.append(data)
    kind=model['api_kind'];params=model.get('parameters',{}).copy();reasoning=params.pop('reasoning_effort',None)
    if kind=='responses':
        content=[{'type':'input_text','text':prompt}]+[{'type':'input_image','image_url':d} for d in image_data]
        payload={'model':model['model'],'input':[{'role':'user','content':content}],'max_output_tokens':limit,**params}
        if reasoning:payload['reasoning']={'effort':reasoning}
        endpoint=model['base_url'].rstrip('/')+'/responses'
    else:
        content=[{'type':'text','text':prompt}]+[{'type':'image_url','image_url':{'url':d}} for d in image_data]
        tokenfield=model.get('token_limit_field') or 'max_completion_tokens'
        payload={'model':model['model'],'messages':[{'role':'user','content':content}],tokenfield:limit,**params}
        if reasoning:payload['reasoning_effort']=reasoning
        endpoint=model['base_url'].rstrip('/')+'/chat/completions'
    return endpoint,payload


def live_request(model,packet,limit,timeout,repair_text=None):
    endpoint,payload=request_payload(model,packet,limit,repair_text)
    key=os.environ.get(model.get('api_key_env','')) if model.get('api_key_env') else None
    if model.get('api_key_env') and not key:raise ValueError('Required API key environment variable is not configured')
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    req=urllib.request.Request(endpoint,data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8'),headers=headers,method='POST')
    start=time.monotonic()
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as r:
            blob=r.read(16*1024*1024+1)
            if len(blob)>16*1024*1024:raise ValueError('Model response exceeds limit')
            data=json.loads(blob)
    except urllib.error.HTTPError as exc:
        # Never log body/headers that could echo credentials. Every provider error is a failed trial.
        raise RuntimeError('Model request HTTP '+str(exc.code)+'; no response body or credentials logged') from None
    elapsed=time.monotonic()-start
    if model['api_kind']=='responses':
        texts=[c.get('text','') for item in data.get('output',[]) if item.get('type')=='message' for c in item.get('content',[]) if c.get('type')=='output_text']
        text=''.join(texts);finished=data.get('status','unknown')
        if data.get('status') not in {'completed'}:raise ValueError('Responses result is not completed; do not grade a partial output')
    else:
        choice=(data.get('choices') or [{}])[0];text=choice.get('message',{}).get('content');finished=choice.get('finish_reason','unknown')
        if finished!='stop':raise ValueError('Chat result did not finish normally; do not grade truncated/tool-call output as JSON')
    if not isinstance(text,str):raise ValueError('No plain text JSON result from endpoint')
    # A provider label is evidence of what it reports, not proof of its actual underlying model.
    return {'text':text,'reported_model':data.get('model'),'response_id':data.get('id'),'finish_status':finished,'usage':data.get('usage'),'latency_seconds':elapsed}


def run_live(suite_path,config_path,outdir,allow_network=False,approve_upload=False,transport=None):
    suite=load_suite(suite_path);conf=validated_config(read_json(config_path),suite)
    if not allow_network or not approve_upload:raise ValueError('Live run requires both --allow-network and --approve-upload for these selected fixture images/endpoints')
    if transport is not None:mode='transport_fixture'  # Tests can never become live evidence just by injecting a fake HTTP function.
    else:mode='live_api_microtasks'
    if transport is None:
        missing=[m['id'] for m in conf['models'] if m.get('api_key_env') and not os.environ.get(m['api_key_env'])]
        if missing:raise ValueError('Credentials not configured for: '+', '.join(missing)+'; no model requests were sent')
    caller=transport or live_request;plan_hash=sha256(suite_path);rows=[];calls=0
    with staged_directory(outdir) as stage:
        write_json(stage/'plan.json',plan(suite_path,config_path))
        write_json(stage/'configuration.json',read_json(config_path))  # Env names only, never credential values.
        schedule=[(m,rr,c) for m in conf['models'] for rr in range(1,conf['repetitions']+1) for c in suite['cases']]
        random.Random(conf['schedule_seed']).shuffle(schedule)
        for model,repetition,case in schedule:
            packet=public_packet(case,suite_path);trial_id=f'{model["id"]}__{case["id"]}__r{repetition:02}';folder=stage/'trials'/trial_id;folder.mkdir(parents=True)
            # Public packet only. Answer key stays in the local grader's source suite.
            write_json(folder/'packet.json',packet);attempts=[];result=None;repair=None
            for attempt in range(conf['max_repair_attempts']+1):
                if calls>=conf['max_requests']:raise ValueError('Request budget exhausted; no hidden retries')
                calls+=1
                try:
                    reply=caller(model,packet,conf['max_output_tokens'],conf['timeout_seconds'],repair)
                    write_json(folder/f'response-{attempt+1}.json',reply)
                    parsed=parse_model_json(reply['text']);result=grade(case,parsed,suite_path)
                    attempts.append({'attempt':attempt+1,'status':'graded','passed':result['passed'],'reported_model':reply.get('reported_model'),'latency_seconds':reply.get('latency_seconds'),'response_id':reply.get('response_id'),'usage':reply.get('usage')})
                    # Semantic errors receive no answer-key feedback. Repair is only transport JSON/structure.
                    break
                except Exception as exc:
                    message=str(exc)
                    for m in conf['models']:
                        key=os.environ.get(m.get('api_key_env',''))
                        if key:message=message.replace(key,'[REDACTED]')
                    attempts.append({'attempt':attempt+1,'status':'failed','error':message})
                    repair='Return a single valid JSON object according to the public task contract. Previous output could not be parsed or processed.'
            row={'trial_id':trial_id,'track':mode,'model_config_id':model['id'],'requested_model':model['model'],'reported_model':next((a.get('reported_model') for a in reversed(attempts) if a.get('reported_model')),None),'case_id':case['id'],'repetition':repetition,'attempts':attempts,'grade':result,'passed':bool(result and result['passed']),'suite_sha256':plan_hash,'public_packet_sha256':sha256(folder/'packet.json')}
            write_json(folder/'trial.json',row);rows.append(row)
        if sha256(suite_path)!=plan_hash:raise ValueError('Suite changed during run')
        report={'format':'ppt-benchmark-run/1.3','track':mode,'status':'completed','suite_id':suite['id'],'suite_sha256':plan_hash,'configuration_sha256':sha256(config_path),'planned_trials':conf['planned_trials'],'executed_trials':len(rows),'planned_matrix':[[m['id'],c['id'],rr] for m in conf['models'] for rr in range(1,conf['repetitions']+1) for c in suite['cases']],'request_attempts':calls,'schedule_seed':conf['schedule_seed'],'environment':fingerprint(),'trials':rows,
                'scope':'Fixed-budget isolated micro-tasks. Does not establish complete-deck, host tool-use, real image-generation, or Office acceptance. Failed/API-error trials remain in denominator.'}
        write_json(stage/'run.json',report);write_json(stage/'summary.json',summarize([report]))
    return report


def summarize(runs):
    if not isinstance(runs,list) or not runs:raise ValueError('Provide at least one run')
    groups={};tracks=set();seen=set()
    for run in runs:
        if run.get('format')!='ppt-benchmark-run/1.3':raise ValueError('Unsupported run report')
        if run.get('planned_trials')!=len(run.get('trials',[])):raise ValueError('Missing trials; cannot silently improve score by omitting failures')
        matrix=run.get('planned_matrix')
        if matrix is not None and sorted(matrix)!=sorted([[t['model_config_id'],t['case_id'],t['repetition']] for t in run['trials']]):raise ValueError('Trial matrix differs from the predeclared plan')
        track=run['track'];tracks.add(track)
        for row in run['trials']:
            identity=(run['suite_sha256'],track,row['trial_id'],run.get('configuration_sha256'))
            if identity in seen:raise ValueError('Duplicate trial evidence; do not count same run twice')
            seen.add(identity)
            key=(track,run['suite_sha256'],row['model_config_id'],row['requested_model'],run.get('configuration_sha256'))
            groups.setdefault(key,[]).append(row)
    rows=[]
    for key,trials in sorted(groups.items()):
        track,suite,config,requested,configuration_sha256=key;n=len(trials);k=sum(t['passed']is True for t in trials);p=k/n;z=1.96
        denom=1+z*z/n;center=(p+z*z/(2*n))/denom;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
        reps={}
        for t in trials:reps.setdefault(t['repetition'],[]).append(t)
        rates=[sum(t['passed']is True for t in batch)/len(batch) for _,batch in sorted(reps.items())]
        reported=sorted({t['reported_model'] for t in trials if t.get('reported_model')})
        errors=sum(t['grade'] is None for t in trials)
        false_positive=0;review_count=0
        for t in trials:
            if t['case_id']=='review-clean-control':review_count+=1;false_positive+=int(t['grade']is not None and not t['passed'])
        rows.append({'track':track,'suite_sha256':suite,'model_config_id':config,'requested_model':requested,'configuration_sha256':configuration_sha256,'reported_models':reported,'trials':n,'passed':k,'failed_or_error':n-k,'api_or_parse_errors':errors,'microtask_pass_fraction':p,'descriptive_wilson_interval_95':[max(0,center-half),min(1,center+half)],'repeat_count':len(reps),'repeat_pass_fractions':rates,'repeat_min':min(rates),'repeat_max':max(rates),'repeat_population_sd':statistics.pstdev(rates),'clean_control_trials':review_count,'clean_control_false_positive_trials':false_positive,
                     'scope':'Descriptive, case-correlated trials; interval is not a population guarantee or visual fidelity percentage.'})
    live=[r for r in rows if r['track']=='live_api_microtasks']
    reported={m for r in live for m in r['reported_models']}
    livegroups=[trials for key,trials in groups.items() if key[0]=='live_api_microtasks']
    matrices=[{(t['case_id'],t['repetition']) for t in ts} for ts in livegroups]
    matrix_complete=bool(matrices) and all(m==matrices[0] for m in matrices)
    envs={json.dumps(r.get('environment',{}),sort_keys=True) for r in runs if r['track']=='live_api_microtasks'}
    stable_identity=all(len(r['reported_models'])==1 for r in live)
    comparable=len(reported)>=2 and all(r['repeat_count']>=3 for r in live) and len({r['suite_sha256'] for r in live})==1 and matrix_complete and len(envs)==1 and stable_identity
    return {'status':'summary_only','groups':rows,'tracks':sorted(tracks),'live_cross_model_repeated_measurements_available':comparable,
            'cross_model_conclusion':'Narrow repeated micro-task measurements are available; inspect equal coverage/config/environment before interpretation.' if comparable else 'No adequate live repeated cross-model basis. Fixture/replay, one model or one repetition cannot establish cross-model stability.',
            'end_to_end_stability':'not_measured_by_this_microtask_runner','ranking':'No overall model ranking generated; compare specific documented test outcomes.'}


def replay(suite_path,responses_path,outdir):
    suite=load_suite(suite_path);responses=read_json(responses_path)
    if set(responses)!=set(c['id'] for c in suite['cases']):raise ValueError('Offline responses must cover every case, including explicit null failures')
    rows=[]
    with staged_directory(outdir) as stage:
        for c in suite['cases']:
            response=responses[c['id']]
            try:result=grade(c,response,suite_path)
            except Exception as exc:result={'passed':False,'checks':[{'id':'grader_error','passed':False,'detail':str(exc)}]}
            rows.append({'trial_id':'offline__'+c['id'],'track':'offline_replay','model_config_id':'none','requested_model':'none','reported_model':None,'case_id':c['id'],'repetition':1,'attempts':[],'grade':result,'passed':result['passed']})
        report={'format':'ppt-benchmark-run/1.3','track':'offline_replay','status':'completed','suite_id':suite['id'],'suite_sha256':sha256(suite_path),'configuration_sha256':sha256(responses_path),'planned_trials':len(rows),'trials':rows,'scope':'Grader exercise from local authored responses; zero model calls, zero cross-model claims'}
        write_json(stage/'run.json',report);write_json(stage/'summary.json',summarize([report]))
    return report


def export_packets(suite_path,outdir):
    suite=load_suite(suite_path)
    with staged_directory(outdir) as stage:
        for c in suite['cases']:
            packet=public_packet(c,suite_path);write_json(stage/(packet['id']+'.packet.json'),packet)
        write_json(stage/'host-metadata.template.json',{'track':'host_import_unverified_identity','model_config_id':'','requested_model':'','reported_model':None,'repetition':1,'tool_budget':None,'office_environment':None,'note':'Fill actual host-reported information only. These packets do not themselves certify that a model ran.'})
        report={'status':'prepared','suite_sha256':sha256(suite_path),'case_count':len(suite['cases']),'network_calls':0,'scope':'Public packets contain no answer keys; host process needs access to the referenced local fixture images. Run offline replay separately; do not rename it live.'};write_json(stage/'export.json',report)
    return report


def deterministic_scene(scene_path,outdir,repetitions=3):
    """Rebuild equivalent serialized inputs; no model and no renderer used."""
    import zipfile,shutil,copy
    from lxml import etree
    from common import walk_objects,resolve_asset
    from build_pptx import build
    from inspect_pptx import inspect
    if type(repetitions)is not int or not 2<=repetitions<=10:raise ValueError('deterministic repetitions must be 2..10')
    scene=read_json(scene_path);origin=sha256(scene_path);deps=set()
    for slide in scene['slides']:
        if slide.get('reference'):deps.add(slide['reference'])
        deps.update(o['asset'] for o in walk_objects(slide['objects']) if o['kind']=='image')
    def semantic_parts(pptx):
        result={}
        def collect(blob,prefix=''):
            import io
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for name in sorted(z.namelist()):
                    if name.startswith('docProps/'):continue
                    data=z.read(name)
                    if name.endswith('.xlsx'):collect(data,prefix+name+'/');continue
                    if name.endswith(('.xml','.rels')):
                        tree=etree.fromstring(data,parser=etree.XMLParser(resolve_entities=False,no_network=True))
                        data=etree.tostring(tree,method='c14n')
                    result[prefix+name]=hashlib.sha256(data).hexdigest()
        collect(pptx.read_bytes());return result
    rows=[];baseline=None
    with staged_directory(outdir) as stage:
        inputs=stage/'inputs';inputs.mkdir()
        for rel in deps:
            if rel.startswith('variant-') or rel=='scene.json':raise ValueError('Dependency conflicts with deterministic test input names')
            src=resolve_asset(scene_path.parent,rel);dst=inputs/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        for i in range(repetitions):
            candidate=inputs/f'variant-{i+1}.json'
            # Formatting and object-key ordering only; arrays preserve semantic draw order.
            text=json.dumps(scene,ensure_ascii=bool(i%2),sort_keys=bool(i%2),indent=None if i%2 else 2,allow_nan=False)
            candidate.write_text(text,encoding='utf-8');pptx=stage/f'build-{i+1}.pptx';build(candidate,pptx)
            parts=semantic_parts(pptx);audit=inspect(pptx,candidate)
            if baseline is None:baseline=parts
            changed=sorted(k for k in set(parts)|set(baseline) if parts.get(k)!=baseline.get(k))
            required=['package','native_content','chart_cache']
            # Preserve exact checker statuses; skipped/not-applicable are not invented passes.
            checks={k:audit['checks'].get(k) for k in required}
            row={'index':i+1,'pptx':pptx.name,'pptx_sha256':sha256(pptx),'semantic_parts_sha256':hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest(),'changed_parts':changed,'serialization_equivalent':not changed,'checker_results':checks}
            rows.append(row);write_json(stage/f'build-{i+1}-audit.json',audit)
        if sha256(scene_path)!=origin:raise ValueError('Source changed during deterministic test')
        report={'format':'ppt-deterministic-execution/1.3','track':'deterministic_no_model','status':'equivalent' if all(r['serialization_equivalent'] for r in rows) else 'difference_detected','source_scene_sha256':origin,'repetitions':repetitions,'environment':fingerprint(),'runs':rows,'model_calls':0,'scope':'Equivalent JSON inputs rebuilt and native ZIP parts compared after XML canonicalization; docProps timestamps excluded, embedded workbooks compared recursively. No Office rendering, no visual or cross-model stability conclusion.'}
        write_json(stage/'deterministic-report.json',report)
    return report


def workflow_record(project,metadata_path,outdir):
    """Capture honest end-to-end evidence from a real toolbox project; identity is a host claim."""
    from workflow_store import load
    from verify_delivery import verify
    from workflow_store import under
    state=load(project);metadata=read_json(metadata_path)
    if not isinstance(metadata,dict) or not metadata.get('requested_model'):raise ValueError('Record actual requested model and host information')
    if any(k.lower() in {'api_key','key','authorization'} for k in metadata):raise ValueError('Do not include credentials in benchmark metadata')
    with staged_directory(outdir) as stage:
        run=state.get('run');gate=None
        if run and all(run.get(k) for k in ['candidate','audit','render','review','comparison']):
            try:gate=verify(under(project,run['candidate']['file']),under(project,run['audit']['file']),under(project,run['render']['file']),under(project,run['review']['file']),under(project,run['comparison']['file']),under(project,run['dir']+'/scene.json'))
            except Exception as exc:gate={'status':'blocked','reason':str(exc)}
        else:gate={'status':'blocked','reason':'No complete pre-existing evidence chain; this collector never fills reviews or edits the project'}
        record={'format':'ppt-workflow-benchmark/1.3','track':'host_workflow_import','model_identity':'host-asserted, not independently verified','metadata':metadata,'project_id':state['project_id'],'skill_version':state.get('skill_version'),'recorded_execution_kind':metadata.get('execution_kind','unverified_host_run'),'workflow_status':state['status'],'task_count':state['task_seq'],'run_count':state['run_seq'],'gate_recheck':gate,'environment':fingerprint(),
                'source_images':[{'id':p['id'],'sha256':p['sha256']} for p in state['pages']],
                'completion':bool(gate and gate.get('status')=='passed'),'scope':'Separate end-to-end evidence track; actual gate rechecked where available. Model identity and human/visual review still require trustworthy host evidence. Not mixed with microtask scores.'}
        write_json(stage/'workflow-record.json',record)
    return record


def workflow_summary(records):
    if not records:raise ValueError('At least one workflow record is required')
    groups={};seen=set()
    for r in records:
        if r.get('format')!='ppt-workflow-benchmark/1.3':raise ValueError('Not a full-workflow record')
        identity=(r['project_id'],r['model_identity'],r['metadata'].get('repetition'))
        if identity in seen:raise ValueError('Duplicate workflow trial')
        seen.add(identity)
        source=json.dumps(r['source_images'],sort_keys=True)
        key=(source,r.get('skill_version'),r['metadata']['requested_model'],r['recorded_execution_kind'])
        groups.setdefault(key,[]).append(r)
    rows=[]
    for key,rs in groups.items():
        rows.append({'source_set_sha256':hashlib.sha256(key[0].encode()).hexdigest(),'skill_version':key[1],'requested_model':key[2],'execution_kind':key[3],'trial_count':len(rs),'complete_evidence_trials':sum(r['completion'] for r in rs),'blocked_or_incomplete_trials':sum(not r['completion'] for r in rs),'task_counts':[r['task_count'] for r in rs],'run_counts':[r['run_count'] for r in rs],'model_identity':'Host assertion; not provider-authenticated','visual_quality':'Requires independent review, not inferred from complete_evidence_trials'})
    return {'track':'host_workflow_import','groups':rows,'scope':'End-to-end evidence availability, kept separate from micro-task API/replay scores. No cross-model quality conclusion without repeated equal-case, equal-tool-environment trials and independent visual review.'}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);s=ap.add_subparsers(dest='action',required=True)
    p=s.add_parser('make-suite');p.add_argument('--outdir',type=Path,required=True)
    for name in ['plan','run']:
        p=s.add_parser(name);p.add_argument('--suite',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
        if name=='run':p.add_argument('--outdir',type=Path,required=True);p.add_argument('--allow-network',action='store_true');p.add_argument('--approve-upload',action='store_true')
    p=s.add_parser('export');p.add_argument('--suite',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('replay');p.add_argument('--suite',type=Path,required=True);p.add_argument('--responses',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('report');p.add_argument('--runs',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True)
    p=s.add_parser('deterministic');p.add_argument('--scene',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True);p.add_argument('--repetitions',type=int,default=3)
    p=s.add_parser('workflow-report');p.add_argument('--records',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True)
    p=s.add_parser('workflow-record');p.add_argument('--project',type=Path,required=True);p.add_argument('--metadata',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    a=ap.parse_args(argv)
    try:
        if a.action=='make-suite':r=make_suite(a.outdir);r={'status':'created','case_count':len(r['cases']),'scope':r['provenance']}
        elif a.action=='plan':r=plan(a.suite,a.config)
        elif a.action=='run':r=run_live(a.suite,a.config,a.outdir,a.allow_network,a.approve_upload);r={k:v for k,v in r.items() if k!='trials'}
        elif a.action=='export':r=export_packets(a.suite,a.outdir)
        elif a.action=='replay':r=replay(a.suite,a.responses,a.outdir);r={k:v for k,v in r.items() if k!='trials'}
        elif a.action=='deterministic':r=deterministic_scene(a.scene,a.outdir,a.repetitions)
        elif a.action=='workflow-record':r=workflow_record(a.project,a.metadata,a.outdir)
        elif a.action=='workflow-report':
            if a.out.exists():raise FileExistsError('Use a new report')
            r=workflow_summary([read_json(f) for f in a.records]);write_json(a.out,r)
        else:
            if a.out.exists():raise FileExistsError('Use a new report file')
            r=summarize([read_json(f) for f in a.runs]);write_json(a.out,r)
        print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except Exception as exc:print(json.dumps({'command_status':'failed','error':str(exc)},ensure_ascii=False,indent=2));return 2

if __name__=='__main__':raise SystemExit(main())
