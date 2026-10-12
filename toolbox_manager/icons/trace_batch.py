"""Independent, immutable project trace drafts; no library promotion or visual verdict."""
from __future__ import annotations
import base64
import hashlib
import json
import time
from pathlib import Path
from jsonschema import Draft202012Validator
from .contracts import TRACE_ITEM
from ..policy import authorize, check_input, plain_path

FORMAT='native-trace-item/1'


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trace_batch(manager, arguments, compute):
    from scripts.workflow_store import locked
    from scripts.common import staged_directory
    if len(encoded(arguments))>16_000_000:raise ValueError('Trace batch input exceeds 16 MB')
    project,_=authorize(manager,arguments['project'])
    rows=[];started=time.monotonic()
    # Use the existing writer lock, including its explicit interrupted-write recovery.
    with locked(project):
        for item in arguments['items']:
            clock=time.monotonic()
            row={'id':item['id']}
            try:
                errors=list(Draft202012Validator(TRACE_ITEM).iter_errors(item))
                if errors:
                    # Schema messages can contain the entire base64 mask. Keep values private.
                    error=errors[0]
                    raise ValueError('Invalid item field /'+'/'.join(map(str,error.path))+' ('+error.validator+')')
                a={k:v for k,v in item.items() if k not in {'id','mask_file'}}
                if 'mask_file' in item:
                    source=check_input(item['mask_file'],project,[])
                    if source.stat().st_size>6_000_000:raise ValueError('Mask file exceeds 6 MB')
                    a['mask']=base64.b64encode(source.read_bytes()).decode('ascii')
                # Equivalent explicit/default options and file/base64 inputs share one draft.
                a={'color':'222222','smoothing':'none','simplify_error_px':0,**a}
                raw=base64.b64decode(a['mask'].split(',',1)[-1],validate=True)
                a['mask']=base64.b64encode(raw).decode('ascii')
                key=digest(encoded({'format':FORMAT,'arguments':a}))
                target=plain_path(project/'assets'/'traces'/key)
                if not target.is_relative_to(project):raise ValueError('Trace output leaves project')
                reused=target.exists()
                if not reused:
                    result=compute(a)
                    payload=encoded(result)
                    group=result['scene_fragment']
                    summary={k:result[k] for k in ('parts','commands','mask_size','smoothing','visual_review')}
                    summary.update(object_id=group['id'],semantic_name=a['semantic_name'],box=a['box'])
                    manifest={'format':FORMAT,'input_sha256':key,'result_sha256':digest(payload),'summary':summary}
                    with staged_directory(target) as stage:
                        (stage/'result.json').write_bytes(payload)
                        (stage/'manifest.json').write_bytes(encoded(manifest))
                manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
                if (manifest.get('format')!=FORMAT or manifest.get('input_sha256')!=key or
                        digest((target/'result.json').read_bytes())!=manifest.get('result_sha256')):
                    raise ValueError('Saved trace changed or is incomplete; preserve it and inspect the project asset')
                row.update(status='succeeded',reused=reused,input_sha256=key,
                    result_file=(target/'result.json').relative_to(project).as_posix(),
                    result_sha256=manifest['result_sha256'],summary=manifest['summary'])
            except Exception as exc:
                row.update(status='failed',error={'code':getattr(exc,'code','trace_item_failed'),
                    'message':str(exc)[:600],'next_action':'Correct this item and retry it with the same id; keep successful result files'})
            row['elapsed_ms']=round((time.monotonic()-clock)*1000,2)
            rows.append(row)
    failed=[row['id'] for row in rows if row['status']=='failed']
    return {'status':('failed' if len(failed)==len(rows) else 'partial') if failed else 'completed','items':rows,'retry_ids':failed,
            'succeeded':len(rows)-len(failed),'failed':len(failed),
            'elapsed_ms':round((time.monotonic()-started)*1000,2),'visual_review':'pending'}
