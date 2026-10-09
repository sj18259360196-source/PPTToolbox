"""Bind explicit source observations to exact page content and dependencies."""
import copy
import hashlib
import json
from common import read_json, sha256, walk_objects
from workflow_store import under, WorkflowError


def binding(project, state, page):
    from workflow_scene import assemble
    slide = assemble({**state, 'pages': [page]})['slides'][0]
    slide = copy.deepcopy(slide)
    files = {page['reference']}
    files.update(u['source']['asset'] for u in slide.get('element_scope', {}).get('units', []) if 'source' in u)
    for obj in walk_objects(slide['objects']):
        if obj.get('asset'):
            files.add(obj['asset'])
        decision = obj.get('generation_decision') or {}
        files.update(decision[k] for k in ('reference', 'drawing') if decision.get(k))
    dependencies = {rel: sha256(under(project, rel)) for rel in sorted(files)}
    payload = {'canvas': state['canvas'], 'slide': slide, 'size': page['size'],
               'dependencies': dependencies}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def observation(project, state, page):
    ref = page.get('source_review')
    if not ref or ref.get('status') != 'passed':
        return None
    if not ref.get('file') or not ref.get('sha256'):
        return None  # Legacy unbound summaries remain readable, never reusable.
    if not any(r['file'] == ref['file'] and r['sha256'] == ref['sha256'] for r in state.get('accepted', [])):
        raise WorkflowError('source_review_changed', 'Source observation is not an accepted task')
    path = under(project, ref['file'])
    if sha256(path) != ref['sha256']:
        raise WorkflowError('source_review_changed', 'Source observation changed')
    record = read_json(path)
    if record['kind'] != 'source_review' or record['target']['slide_id'] != page['id'] or record['result']['status'] != 'passed':
        raise WorkflowError('source_review_changed', 'Source observation identity changed')
    packet_path = under(project, 'workflow/tasks/' + record['task_id'] + '/packet.json')
    if sha256(packet_path) != record['packet_sha256']:
        raise WorkflowError('source_review_changed', 'Source observation packet changed')
    packet = read_json(packet_path)
    saved = packet['context'].get('source_binding')
    if not saved:
        return None  # Older observations have no complete dependency signature.
    if packet['project_id'] != state['project_id'] or saved != binding(project, state, page):
        raise WorkflowError('source_review_changed', 'Source observation no longer matches the page')
    for item in packet['input_files']:
        if sha256(under(project, item['file'])) != item['sha256']:
            raise WorkflowError('source_review_changed', 'Source observation input changed')
    return {'task_id': record['task_id'], 'binding': saved}


def retain(project, state, old, new, canvas):
    evidence = observation(project, state, old)
    if evidence and evidence['binding'] == binding(project, {**state, 'canvas': canvas}, new):
        new['source_review'] = copy.deepcopy(old['source_review'])
        new['source_review_reuse'] = {**evidence, 'scope': 'identical_page_and_dependencies'}
        return True
    return False


def verify(project, state):
    for page in state['pages']:
        if (page.get('source_review') or {}).get('status') == 'passed':
            evidence = observation(project, state, page)
            reused = page.get('source_review_reuse')
            if reused and (not evidence or any(reused.get(k) != evidence[k] for k in ('task_id', 'binding'))):
                raise WorkflowError('source_review_changed', 'Reused source observation identity changed')
