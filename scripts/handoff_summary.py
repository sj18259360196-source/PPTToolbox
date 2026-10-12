"""Derived continuation summary. Never promotes a recorded observation to acceptance."""
from pathlib import Path
import json


def continuation(state):
    if state.get('operation') or state.get('failure'):
        return 'Inspect managed status, recovery and logs before another write. Do not replay unknown effects.'
    if state.get('status')=='awaiting_revision' and not state.get('active_task'):
        return 'Inspect current findings; use rebuild_revise with explicit slide/region and reason, then rebuild_next.'
    if state.get('status')=='delivered':
        return 'Present the existing delivery. A further edit requires an explicit revision; do not repeat finish.'
    if state.get('active_task'):
        return 'Bind this project, refresh rebuild_status, then use the current task identity and required views.'
    return 'Bind this project, inspect rebuild_status, then rebuild_next; next may build or render ready work.'


def render(root, state, brief):
    lines=['# Current PPT handoff', '', 'Derived summary. workflow/state.json remains authoritative.', '',
           '- Project '+state['project_id'], '- Revision '+str(state['revision']),
           '- Workflow '+brief['workflow_status'],
           '- Ready pages '+str(brief['pages_ready'])+'/'+str(brief['pages_total']), '',
           continuation(state), '',
           'Use governed rebuild tools. No token is saved here. Refresh identity after rebinding.',
           'Only current required images need opening; a new context must view them before claiming observations.',
           'Preserve source text, native edit requirements, full/local review and actual Office edit/save/reopen gates.', '']
    task=state.get('active_task')
    if task:
        lines+=['## Current task',json.dumps({k:task[k] for k in ('id','kind','target','base_revision','packet') if k in task},ensure_ascii=False),'']
    run=state.get('run') or {}
    artifacts={k:run[k] for k in ('id','dir','candidate','audit','render','comparison','gate') if k in run}
    if state.get('delivery'):artifacts['delivery']=state['delivery']
    if artifacts:lines+=['## Current artifacts',json.dumps(artifacts,ensure_ascii=False),'']
    if run.get('reviews'):
        from edit_summary import summarize
        try:
            edit_summary=summarize(root,state)
            tests=edit_summary.pop('tests')
            limitations=edit_summary.pop('limitations')
            edit_summary.update(test_count=len(tests),limitation_count=len(limitations),
                                limitations=limitations[:6],limitations_truncated=len(limitations)>6)
            edit_summary['details']='Use toolbox_project_inspect action=edits or read the bound record for all operations.'
            lines+=['## Recorded edit operations and limitations',
                    json.dumps(edit_summary,ensure_ascii=False),'']
        except (OSError,ValueError,KeyError) as exc:
            lines+=['## Recorded edit operations and limitations',
                    'Summary unavailable; inspect authoritative edit evidence. '+str(exc),'']
    refs=[]
    for page in state.get('pages',[]):
        if page.get('source_review'):
            refs.append({'scope':{'slide_id':page['id'],'kind':'source_review'},'record':page['source_review']})
    refs.extend({'scope':{'review_key':key},'record':value} for key,value in run.get('reviews',{}).items())
    if refs:
        lines+=['## Current observation records',
                'These are recorded observations, not fresh verification. Full records retain findings and object IDs.',
                'Current record count '+str(len(refs))+'. Showing the latest 12; full index is pages[].source_review and run.reviews in workflow/state.json.',
                json.dumps(refs[-12:],ensure_ascii=False),'']
        for entry in refs[-12:]:
            record=entry['record'];rel=record.get('file')
            if not rel:continue
            try:
                from workflow_store import under
                path=under(Path(root),rel)
                if path.stat().st_size>262144:
                    lines.append('Detail deferred to '+rel);continue
                value=json.loads(path.read_text(encoding='utf-8'))
                result=value.get('result',{})
                selected={k:result[k] for k in ('status','note','observations','checks') if k in result}
                text=json.dumps({'scope':entry['scope'],'record':rel,'reported_findings':selected},ensure_ascii=False)
                lines.append(text if len(text)<=2400 else text[:2400]+' [summary clipped; read full record]')
            except (OSError,ValueError,KeyError):
                lines.append('Record unreadable; inspect authoritative state and '+str(rel))
    if state.get('operation') or state.get('failure'):
        lines+=['','## Unresolved execution',json.dumps({k:state[k] for k in ('operation','failure') if state.get(k)},ensure_ascii=False)]
    return '\n'.join(lines)+'\n'
