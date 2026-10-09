"""Deterministic impact projection; never changes call or workflow outcomes."""
from copy import deepcopy


def assess(state):
    activity = state.get('activity', {})
    phase = state.get('phase', {})
    task = activity.get('task') or {}
    delivered = (phase.get('status') == 'finished' and phase.get('artifact_state') == 'present'
                 and not task.get('id'))
    calls = activity.get('calls', [])
    result = []
    for original in activity.get('issues', []):
        issue = deepcopy(original)
        issue.update(impact='blocks_current', impact_reason='当前操作仍需处理')
        if issue.get('state') != 'open':
            issue.update(impact='historical', impact_reason='历史处置已记录')
        elif issue.get('status') == 'outcome_unknown':
            issue.update(impact='needs_assessment', impact_reason='缺少终态，先核对回执与产物，不重放写入')
        elif 'no_results' in {issue.get('status'), issue.get('error_code'), issue.get('message')}:
            issue.update(impact='informational', severity='info', impact_reason='搜索已完成，没有匹配素材')
        elif (issue.get('recovery') or {}).get('outcome') == 'rejected':
            before, after = issue.get('revision_before'), issue.get('revision_after')
            unchanged = isinstance(before, int) and after == before
            later = [c for c in calls if c.get('tool') == issue.get('tool')
                     and c.get('project') == issue.get('project') and c.get('status') in {'completed','ok','passed'}
                     and isinstance(c.get('revision_after'), int) and unchanged
                     and c['revision_after'] > before and c.get('at','') > issue.get('at','')]
            evidence = [c['evidence_id'] for c in later if c.get('evidence_id')] or issue.get('related_evidence_ids',[])
            if unchanged and delivered and evidence:
                issue.update(impact='historical', impact_reason='此尝试被拒绝且未推进版本；后续操作成功，项目已有交付',
                             related_evidence_ids=evidence)
        issue['attention_required'] = issue['impact'] in {'blocks_current','needs_assessment'}
        result.append(issue)
    return {'issues': result, 'attention': [i for i in result if i['attention_required']],
            'history': [i for i in result if not i['attention_required']], 'delivered': delivered}


def handoff(state):
    view = assess(state)
    phase = state.get('phase', {})
    return {'format': 'ppttool-assistance/1', 'basis_sequence': state.get('sequence'),
            'project_id': state.get('project_id'), 'phase': phase,
            'task': state.get('activity', {}).get('task'),
            'current_action': ('等待用户认可交付' if view['delivered'] else phase.get('next_action') or '核对当前任务'),
            'attention': [{k:i.get(k) for k in ('id','tool','title','impact','impact_reason','evidence_id','next_action')}
                          for i in view['attention']],
            'historical_count': len(view['history']),
            'artifacts': phase.get('artifacts', []),
            'evidence_ids': list(dict.fromkeys(i['evidence_id'] for i in view['issues'] if i.get('evidence_id'))),
            'authority': 'assistance_only_no_workflow_transition'}
