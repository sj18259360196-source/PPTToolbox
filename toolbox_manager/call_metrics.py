"""Comparable local call measurements. Host traffic and model usage remain unknown."""
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def fingerprint(arguments):
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False,
                                    default=str, separators=(',', ':')).encode('utf-8')).hexdigest()


def finish(record, result, began):
    error=result.get('error',{}) if isinstance(result,dict) else {}
    if isinstance(error,dict) and isinstance(error.get('code'),str):
        record['error_code']=error['code']
    visible = ({k: v for k, v in result.items() if k != 'call_metrics'}
               if isinstance(result, dict) else result)
    payload = ({k: v for k, v in visible.items() if k not in {'stdout','stderr'}}
               if isinstance(visible,dict) else visible)
    metrics = {'format': 'ppt-call-metrics/1', 'elapsed_seconds': max(0, time.perf_counter()-began),
               'result_json_utf8_bytes': (len(json.dumps(visible, ensure_ascii=False, default=str).encode('utf-8'))
                                          if result is not None else None),
               'payload_json_utf8_bytes': (len(json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'))
                                           if result is not None else None),
               'result_scope': 'service_result_excluding_metrics',
               'host_network_bytes': None, 'model_input_tokens': None}
    if (isinstance(result,dict) and isinstance(result.get('items'),list)
            and type(result.get('succeeded')) is int and type(result.get('failed')) is int):
        rows=result['items']
        metrics['item_counts']={'succeeded':sum(row.get('status')=='succeeded' for row in rows),
                               'failed':sum(row.get('status')=='failed' for row in rows),
                               'reused':sum(row.get('reused') is True for row in rows)}
        metrics['item_failure_codes']=dict(Counter(str(row.get('error',{}).get('code','unknown'))
                                                  for row in rows if row.get('status')=='failed'))
    record['metrics'] = metrics
    return metrics


def summarize(project, limit=2000):
    from scripts.workflow_timing import summarize as workflow_timing
    root = Path(project).resolve()
    folder = root/'logs/tool-calls'
    files = sorted([*folder.glob('*/call.json'), *folder.glob('*/activity.json')],
                   key=lambda p: (p.parent.name, p.name))
    total_records = len(files)
    records, unreadable, disk_bytes = {}, 0, 0
    for path in files[:limit]:
        try:
            if not path.resolve().is_relative_to(root) or path.stat().st_size > 16*1024*1024:
                unreadable += 1
                continue
            disk_bytes += path.stat().st_size
            row = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(row, dict):
                raise ValueError('Expected a call record')
            cid = row.get('call_id') or path.parent.name
            if not isinstance(cid, str):
                raise ValueError('Expected a string call ID')
            if cid not in records or path.name == 'call.json':
                records[cid] = row
        except (OSError, ValueError, TypeError):
            unreadable += 1
    statuses, tools, failures = Counter(), Counter(), Counter()
    timed, elapsed, measured, returned = 0, 0., 0, 0
    item_counts,item_failures=Counter(),Counter()
    for row in records.values():
        statuses[str(row.get('command_status') or 'unknown')] += 1
        tools[str(row.get('tool_id') or 'unknown')] += 1
        if isinstance(row.get('error_code'), str):
            failures[row['error_code']] += 1
        metrics = row.get('metrics') or {}
        if not isinstance(metrics, dict):
            metrics = {}
        for values, counter in ((metrics.get('item_counts'),item_counts),(metrics.get('item_failure_codes'),item_failures)):
            if isinstance(values,dict):counter.update({k:v for k,v in values.items() if type(v) is int and v>=0})
        seconds = metrics.get('elapsed_seconds')
        if seconds is None and row.get('started_at') and row.get('ended_at'):
            try:
                seconds = (datetime.fromisoformat(row['ended_at'])-datetime.fromisoformat(row['started_at'])).total_seconds()
            except (ValueError, TypeError):
                pass
        if type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0:
            timed += 1
            elapsed += seconds
        size = metrics.get('result_json_utf8_bytes')
        if (metrics.get('format') == 'ppt-call-metrics/1' and metrics.get('result_scope')=='service_result_excluding_metrics'
                and type(size) is int and size >= 0):
            measured += 1
            returned += size
    return {'format': 'ppt-call-summary/1', 'calls': len(records), 'record_files': total_records,
            'workflow_timing': workflow_timing(root),
            'limited': total_records > limit, 'unreadable_records': unreadable,
            'status_counts': dict(statuses), 'tool_counts': dict(tools), 'failure_codes': dict(failures),
            'item_counts':dict(item_counts),'item_failure_codes':dict(item_failures),
            'timed_calls': timed, 'tool_elapsed_seconds': elapsed,
            'measured_result_calls': measured, 'result_json_utf8_bytes': returned if measured else None,
            'scanned_record_file_bytes': disk_bytes,
            'host_network_bytes': None, 'model_input_tokens': None,
            'note': 'Call IDs are deduplicated. Durations may overlap and are not end-to-end task time. '
                    'Result JSON includes stdio and excludes metrics; the MCP envelope is not measured. Record file bytes are a separate disk measure. '
                    'Missing historical measurements remain unknown.'}
