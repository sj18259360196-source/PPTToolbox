"""Object-level recorded edit tests. Unknown and historical coverage stays explicit."""
from pathlib import Path

if __package__:
    from .common import read_json, sha256, walk_objects
else:
    from common import read_json, sha256, walk_objects


TEXT = {'type': 'string', 'minLength': 1}
TEST_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'object_id': TEXT, 'slide_id': TEXT, 'operation': TEXT,
    'scope': {'enum': ['required', 'stress']},
    'status': {'enum': ['passed', 'needs_changes', 'blocked']},
    'tested_value': {'type': ['string', 'number', 'boolean', 'array', 'object', 'null']},
    'finding': TEXT, 'required_adjustment': TEXT,
    'evidence_files': {'type': 'array', 'items': TEXT, 'minItems': 1, 'uniqueItems': True}},
    'required': ['object_id', 'slide_id', 'operation', 'scope', 'status', 'finding', 'evidence_files']}


def validate_tests(result, scene):
    from validation_checks import Checks
    import jsonschema
    checks = Checks()
    inventory = {(s['id'], o['id']) for s in scene['slides'] for o in walk_objects(s['objects'])}
    files = {str(Path(f).resolve()) for f in result.get('files', [])}
    for i, row in enumerate(result.get('edit_tests', [])):
        path = '/edit_tests/'+str(i)
        errors = list(jsonschema.Draft202012Validator(TEST_SCHEMA).iter_errors(row))
        if errors:
            for error in errors:
                checks.add(error.message, path+'/'+('/'.join(map(str,error.absolute_path))), 'edit_test_schema')
            continue
        oid = row['object_id']
        if (row['slide_id'], oid) not in inventory:
            checks.add('Edit test must name a current slide and object', path+'/object_id','edit_target',oid)
        if not {str(Path(f).resolve()) for f in row['evidence_files']} <= files:
            checks.add('Edit evidence must be included in result.files',path+'/evidence_files','edit_evidence',oid)
        if row['status'] != 'passed' and not row.get('required_adjustment'):
            checks.add('A failed or blocked edit test needs the required adjustment',path+'/required_adjustment','edit_adjustment',oid)
        if row['scope']=='required' and row['status']!='passed' and result['status']=='passed':
            checks.add('Required edit failure cannot be submitted as passed',path+'/status','edit_acceptance',oid)
    checks.finish()


def summarize(project, state):
    from workflow_store import under
    root = Path(project)
    result = {'format':'ppt-edit-summary/1','coverage':'not_recorded','all_objects_tested':False,
              'tests':[],'actions':[],'limitations':[],'reported_status':None,'legacy_note':None}
    for key, record in (state.get('run') or {}).get('reviews',{}).items():
        if key != 'editable_behavior':
            continue
        path = under(root,record['file'])
        if path.stat().st_size > 16*1024*1024:
            raise ValueError('Edit summary record exceeds inspection limit')
        # Hash-bound records only; do not silently summarize mutated evidence.
        if sha256(path)!=record['sha256']:
            raise ValueError('Edit summary record changed: '+record['file'])
        saved = read_json(path)
        if saved.get('kind')!='editable_behavior':
            continue
        observed = saved['result']
        tests = observed.get('edit_tests',[])
        result.update(coverage='sampled_tests' if tests else 'legacy_actions_and_note',
                      record=record,reported_status=observed.get('status'),tests=tests,
                      stored_evidence=saved.get('attachments',[]),
                      actions=observed.get('actions',[]),legacy_note=observed.get('note'),
                      limitations=[t for t in tests if t['status']!='passed'])
    result['note']='Recorded sampled operations only. A successful content readback is not layout acceptance. '
    result['note']+='Historical notes are retained verbatim; no character limit or untested capability is inferred.'
    return result


def render(summary):
    """Human-readable disclosure beside the machine-readable delivery summary."""
    def cell(value):
        return str(value or '').replace('|','\\|').replace('\r',' ').replace('\n',' ')
    lines=['## 编辑测试与限制','',
           '记录只覆盖实际提交的抽测操作。完整测试值和证据路径保存在 edit-summary.json。','']
    if summary['tests']:
        lines+=['| 页面与对象 | 操作 | 测试范围 | 结果 | 发现与所需调整 |',
                '| --- | --- | --- | --- | --- |']
        for row in summary['tests']:
            values=[row['slide_id']+'/'+row['object_id'],row['operation'],row['scope'],row['status'],
                    row['finding']+' '+row.get('required_adjustment','')]
            lines.append('| '+' | '.join(cell(v) for v in values)+' |')
    else:
        lines+=['旧记录未逐对象列出测试结果，不能据此判定整份 PPT 的编辑能力。','']
        for row in summary.get('actions',[]):
            lines.append('- '+cell(row.get('kind'))+' '+cell(row.get('note')))
    if summary.get('legacy_note'):
        lines+=['','原测试备注','',summary['legacy_note']]
    return '\n'.join(lines)+'\n'
