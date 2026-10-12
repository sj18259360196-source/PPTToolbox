"""Apply user-saved production preferences without rewriting completed regions."""
from __future__ import annotations
import copy
from pathlib import Path


def unit_affected(unit, changed):
    if changed & {'font_matching','text_layout'} and (unit.get('required_edit') == 'text' or unit.get('content_type') in {'page_text','standard_title'}):
        return True
    need = unit.get('material_requirement') or {}
    quality = need.get('source_qualification') or {}
    clean_reuse = (unit.get('material_route') == 'preserve_source' and need.get('source_origin') == 'independent_asset'
                   and quality.get('complete_subject') is True and quality.get('page_artifacts') == 'none')
    return ('illustration_mode' in changed and unit.get('content_type') in
            {'simple_illustration','complex_illustration','decorative_title','existing_asset'}
            and need.get('route_constraint','auto') == 'auto' and need.get('fidelity') != 'exact'
            and unit.get('required_edit') not in {'preserve','data','text'} and not clean_reuse)


def apply(project, settings, scope='unfinished', selected_objects=None):
    from workflow_store import locked, load, save, WorkflowError
    from production_settings import snapshot, validate_values
    import workflow as wf
    values = validate_values(settings['values'])
    current = snapshot(values, revision=settings.get('revision', 0), source=settings.get('source', 'project'))
    selected_objects = selected_objects or []
    if scope not in {'unfinished', 'selected_completed'}:
        raise ValueError('Unknown production settings application scope')
    with locked(Path(project)):
        state = load(Path(project))
        if state.get('operation'):
            raise WorkflowError('writer_busy', 'Inspect the pending operation before applying production settings')
        old = state.get('production_settings')
        if scope == 'unfinished' and old and old.get('revision') == current['revision'] and old.get('effective_sha256') == current['effective_sha256']:
            return wf.brief(state)
        selected = {}
        for item in selected_objects:
            if not isinstance(item, dict) or not item.get('slide_id') or not item.get('region_id'):
                raise ValueError('Select completed regions with slide_id and region_id')
            page = wf._page(state, item['slide_id'])
            if page.get('imported_slide') is not None:
                raise WorkflowError('settings_revision_required', 'Reopen the imported page through rebuild_revise before applying settings')
            if item['region_id'] not in {r['id'] for r in (page.get('plan') or {}).get('regions', [])}:
                raise ValueError('Selected production region does not exist')
            selected.setdefault(item['slide_id'], set()).add(item['region_id'])
        if scope == 'selected_completed' and not selected:
            raise ValueError('Select at least one completed region')
        changed = {k for k,v in values.items() if not old or old.get('values', {}).get(k) != v}
        affected = []
        for page in state['pages']:
            if page.get('imported_slide') is not None:
                continue
            plan = page.get('plan')
            completed = set(page.get('fragments', {}))
            requested = selected.get(page['id'], set()) if scope == 'selected_completed' else set()
            if plan:
                unfinished = {r['id'] for r in plan['regions']} - completed
                relevant = set()
                for region in plan['regions']:
                    rid = region['id']
                    units = [u for u in (plan.get('element_scope') or {}).get('units', []) if u['region_id'] == rid]
                    if (not units and changed) or any(unit_affected(u, changed) for u in units):
                        relevant.add(rid)
                targets = (unfinished & relevant) | requested
                if not targets:
                    continue
                keep = completed - requested
                prior_settings = page.get('production_settings', old)
                retained = page.setdefault('region_production_settings', {})
                for rid in keep:
                    if prior_settings:
                        retained.setdefault(rid, copy.deepcopy(prior_settings))
                for rid in targets:
                    retained.pop(rid, None)
                page['settings_preserved_plan'] = copy.deepcopy(plan)
                page['settings_preserved_regions'] = sorted(keep)
                page['previous_element_scope'] = copy.deepcopy(plan.get('element_scope'))
                for rid in requested:
                    if rid in page['fragments']:
                        page.setdefault('previous_fragments', {})[rid] = page['fragments'].pop(rid)['raw']
                page['plan'] = None
                page.pop('review_plan', None)
            else:
                targets = None
            page['production_settings'] = copy.deepcopy(current)
            page['source_review'] = None
            page['planning_state'] = 'awaiting_replanning'
            for job in state.get('asset_jobs', []):
                if job['slide_id'] == page['id'] and job['status'] != 'completed' and (targets is None or job['region_id'] in targets):
                    job['status'] = 'cancelled'
            affected.append(page['id'])
        state['production_settings'] = current
        if affected:
            wf._invalidate_run(state, 'production_settings_changed')
        else:
            wf._cancel(state, 'production_settings_version_updated')
        save(Path(project), state, 'production_settings_applied', {
            'settings_revision': current['revision'], 'scope': scope,
            'changed_fields': sorted(changed), 'affected_pages': affected,
            'selected_regions': selected_objects})
        return {**wf.brief(state), 'production_settings_applied': current, 'affected_pages': affected}


def validate_retained_plan(page, plan):
    old = page.get('settings_preserved_plan')
    keep = set(page.get('settings_preserved_regions', []))
    if not old or not keep:
        return
    for rid in keep:
        if next((r for r in old['regions'] if r['id']==rid), None) != next((r for r in plan['regions'] if r['id']==rid), None):
            raise ValueError('production_settings: retain completed region geometry; explicitly select it for revision to change it')
    def units(p):
        return {u['id']:u for u in (p.get('element_scope') or {}).get('units', []) if u['region_id'] in keep}
    if units(old) != units(plan):
        raise ValueError('production_settings: retain completed unit requirements; explicitly revise affected regions')


def review_required(settings):
    return bool(settings and settings.get('values'))


def affects_active(state, settings, pending):
    """Defer unrelated preference changes until the current task completes."""
    task = state.get('active_task')
    if not task:
        return True
    target = task['target']
    if task['kind'] in {'page_plan'}:
        return True
    if task['kind'] not in {'region_objects','asset_material'}:
        return any(r['slide_id'] == target.get('slide_id') for r in pending.get('selected_objects', []))
    sid, rid = target.get('slide_id'), target.get('region_id')
    if task['kind'] == 'asset_material':
        job = next(j for j in state['asset_jobs'] if j['id']==target['job_id'])
        sid,rid = job['slide_id'],job['region_id']
    if any(r['slide_id']==sid and r['region_id']==rid for r in pending.get('selected_objects',[])):
        return True
    page = next(p for p in state['pages'] if p['id']==sid)
    units = [u for u in ((page.get('plan') or {}).get('element_scope') or {}).get('units',[]) if u['region_id']==rid]
    if not units:
        return True
    changed = set(pending.get('changed_fields',[]))
    return any(unit_affected(u, changed) for u in units)


REVIEW_SCHEMA = {'type':'object','additionalProperties':False,
    'required':['settings_sha256','checks'], 'properties':{
        'settings_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
        'checks':{'type':'object','additionalProperties':False,
            'required':['illustration_mode','font_matching','text_layout'],
            'properties':{k:{'type':'object','additionalProperties':False,'required':['status','note'],
                'properties':{'status':{'enum':['passed','needs_changes','blocked','not_applicable']},
                              'note':{'type':'string','minLength':1}}}
                for k in ['illustration_mode','font_matching','text_layout']}}}}


def review_template(settings):
    return {'settings_sha256':settings['effective_sha256'],
            'checks':{k:{'status':'blocked','note':''} for k in ['illustration_mode','font_matching','text_layout']}}


def validate_review(settings, result, objects=None):
    if not review_required(settings) and 'production_review' not in result:
        return
    import jsonschema
    row = result.get('production_review')
    errors = list(jsonschema.Draft202012Validator(REVIEW_SCHEMA).iter_errors(row))
    if errors:
        raise ValueError('production_settings: include the current production_review and setting-specific checks; ' + errors[0].message)
    if not settings or row['settings_sha256'] != settings['effective_sha256']:
        raise ValueError('production_settings: review must bind the current effective settings')
    passed = result.get('status') == 'passed' or (result.get('checks') and all(c['status']=='passed' for c in result['checks'].values()))
    if any(not c['note'].strip() for c in row['checks'].values()):
        raise ValueError('production_settings: record actual setting-specific observations')
    if objects:
        from common import walk_objects
        if any(o.get('kind') == 'text' for o in walk_objects(objects)) and any(
                row['checks'][k]['status'] == 'not_applicable' for k in ('font_matching','text_layout')):
            raise ValueError('production_settings: native text requires font and text-layout review')
    if passed and any(c['status'] not in {'passed','not_applicable'} for c in row['checks'].values()):
        raise ValueError('production_settings: unresolved setting-specific defect cannot pass')
