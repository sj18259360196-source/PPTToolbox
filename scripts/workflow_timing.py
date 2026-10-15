"""Workflow wall time from persisted events, separate from summed call durations."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .project_layout import read_record, safe_path
else:
    from project_layout import read_record, safe_path


def summarize(project, observed_at=None):
    try:
        state = read_record(safe_path(Path(project), 'workflow/state.json'))
    except (OSError, ValueError) as exc:
        return {'available': False, 'reason': str(exc)}
    def timestamp(value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError('Timing needs an explicit time zone')
        return parsed
    rows, issues, operations, tasks = [], [], {}, {}
    history = state.get('history', [])
    counts = Counter(row.get('event', 'unknown') for row in history)
    end = observed_at or datetime.now(timezone.utc).isoformat()
    if state.get('status') == 'delivered':
        deliveries = [r for r in history if r.get('event') == 'delivery_created']
        end = deliveries[-1]['at'] if deliveries else state.get('updated_at')
    elapsed = None
    try:
        elapsed = (timestamp(end)-timestamp(state['created_at'])).total_seconds()
        if elapsed < 0:
            raise ValueError('Clock moved backwards')
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(str(exc)); elapsed = None
    for row in history:
        event, detail = row.get('event'), row.get('detail') or {}
        if event == 'operation_started':
            key = detail.get('kind')
            if key in operations: issues.append('Unclosed operation: '+str(key))
            operations[key] = row
        elif event in {'operation_completed', 'operation_failed'}:
            key = detail.get('kind') or detail.get('stage')
            begin = operations.pop(key, None)
            if begin:
                try:
                    seconds = (timestamp(row['at'])-timestamp(begin['at'])).total_seconds()
                    if seconds < 0: raise ValueError('Clock moved backwards')
                    rows.append({'kind': key, 'status': 'completed' if event.endswith('completed') else 'failed',
                                 'started_at': begin['at'], 'ended_at': row['at'], 'elapsed_seconds': seconds})
                except (TypeError, ValueError, KeyError) as exc: issues.append(str(exc))
        elif event == 'task_issued':
            tasks[detail.get('id') or detail.get('task_id')] = row
        elif event == 'task_accepted':
            tasks.pop(detail.get('id'), None)
    return {'format': 'ppt-workflow-timing/1', 'available': True,
            'started_at': state.get('created_at'), 'ended_at': end,
            'complete': state.get('status') == 'delivered', 'workflow_elapsed_seconds': elapsed,
            'operation_windows': rows, 'unclosed_operations': sorted(str(k) for k in operations),
            'event_counts': dict(counts), 'rework_counts': {k: counts[k] for k in
                ('explicit_retry','region_reopened','imported_region_reopened','review_reopened','scene_replaced','candidate_replaced')},
            'issues': issues, 'model_active_seconds': None, 'user_wait_seconds': None,
            'scope': 'Wall time includes reasoning, tool work, pauses and user waiting. Operation windows use recorded timestamps; no speedup inferred from overlapping call sums.'}
