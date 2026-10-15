"""Current-task request construction and public client defaults; no auto-approval."""
from __future__ import annotations

import copy
import sys
from pathlib import Path


def defaults(command, arguments):
    result = dict(arguments)
    if command in {'start', 'next', 'status', 'submit'}:
        result.setdefault('response_detail', 'compact')
    if command == 'submit':
        result.setdefault('return_next', True)
    return result


def exit_code(result):
    """A successful transport is not a successful prerequisite for the next command."""
    if not isinstance(result, dict):
        return 0
    if result.get('returncode'):
        return result['returncode']
    if result.get('valid') is False:
        return 2
    if result.get('command_status') in {'failed', 'tool_failed', 'invalid_arguments', 'permission_denied',
                                       'action_required', 'awaiting_capability', 'timeout', 'outcome_unknown'}:
        return 2
    if (result.get('workflow_status') == 'tool_failed' or result.get('next_error')
            or (result.get('recovery') or {}).get('outcome') == 'accepted_next_failed'):
        return 2
    return 0


def prepare(project):
    """Return a fresh pinned draft. Callers must authorize the project before entry."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    from common import read_json, sha256
    from workflow_store import load, under, check_packet, WorkflowError
    from workflow import _template
    project = Path(project).resolve()
    state_path = project/'workflow/state.json'
    before = sha256(state_path)
    if (project/'workflow/writer.lock').exists():
        raise WorkflowError('writer_busy', 'Read the current task after its writer completes')
    state = load(project)
    task = state.get('active_task')
    if not task:
        raise WorkflowError('no_active_task', 'Read status or next; no current submission to prepare')
    check_packet(project, state, task)
    packet = read_json(under(project, task['packet']))
    context = packet['context']
    result = _template(task['kind'], context)
    preparation = None
    if task['kind'] == 'editable_behavior':
        from edit_preparation import build as prepare_edits
        run = state['run']
        scene_path = under(project, run['dir']+'/scene.json')
        candidate_path = under(project, run['candidate']['file'])
        if (under(project, context['scene']) != scene_path
                or under(project, context['candidate']) != candidate_path):
            raise WorkflowError('stale_task', 'Edit task does not name the current frozen scene and candidate')
        preparation = prepare_edits(scene_path, candidate_path, context['required_edit_actions'],
                                    project_id=state['project_id'], run_id=run['id'])
        issued = context.get('edit_preparation') or {}
        if issued.get('binding') == preparation['binding']:
            issued_batches = {b['id']: b for b in issued.get('operation_batches', [])}
            pinned_files = {item['file'] for item in task['inputs']}
            for batch in preparation['operation_batches']:
                previous = issued_batches.get(batch['id'], {})
                if (previous.get('operations') == batch['operations']
                        and previous.get('operations_file') in pinned_files):
                    batch.update({key: copy.deepcopy(previous[key]) for key in ('operations_file', 'plan_arguments')
                                  if key in previous})
    if task['kind'] in {'editable_behavior', 'reproducibility'}:
        result['actions'] = [{'kind':kind, 'note':''} for kind in context['required_edit_actions']]
    if task['kind'] in {'review_full', 'review_local'} and context.get('review_bundle'):
        result['additional_reviews'] = [
            {'region_id':row['region_id'], 'result':_template('review_local', row)}
            for row in context['review_bundle']]
    # Keep the same request usable by preflight and submit. Transport defaults
    # are applied by their public entry points, not mixed into the authored result.
    request = {'project':str(project), 'task_id':task['id'],
        'token':task['token'], 'base_revision':task['base_revision'], 'result':result}
    check_packet(project, state, task)
    if before != sha256(state_path) or (project/'workflow/writer.lock').exists():
        raise WorkflowError('stale_task', 'Task changed during preparation; read the current task')
    return {'format':'ppt-submission-draft/1', 'kind':task['kind'], 'request':request,
        **({'edit_preparation': preparation} if preparation is not None else {}),
        'submit_defaults':defaults('submit', {}),
        'validation_status':'not_run', 'state_changed':False,
        'binding':{'state_sha256':before, 'packet_sha256':task['packet_sha256']},
        'choices':{'action_kinds':context.get('required_edit_actions', []),
                   'component_scope':[{'unit_id':u['id'], 'region_id':u['region_id'],
                        'required_edit':u.get('required_edit'), 'material_route':u.get('material_route')}
                       for u in (context.get('element_scope') or {}).get('units', [])],
                   'submission_constraints':copy.deepcopy(context.get('submission_constraints', {}))},
        'instructions':['Edit request.result only. Task identity is pinned and cannot be rebound after authoring.',
            'Draft observations are empty and review statuses blocked. View required files before recording conclusions.',
            'Each additional review needs its own observations. Remove unfinished entries; they remain pending.',
            'Validate the authored request with rebuild_validate_response, then submit only if valid=true. '
            'Submission rechecks current state and files. Never replay an accepted or unknown submission.']}
