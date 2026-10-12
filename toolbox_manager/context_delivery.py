"""Lossless current-task delivery and local text accounting. No host token estimates."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from .storage import digest


def text_size(value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return {'json_chars': len(text), 'json_utf8_bytes': len(text.encode('utf-8'))}


def compact_task(task, packet, template):
    # Retain every context field, including future task-specific constraints.
    # Only duplicate tool descriptors are shortened. Packets stay immutable.
    task['context'] = copy.deepcopy(packet['context'])
    task['response'] = copy.deepcopy(template)
    task['response_detail'] = 'compact'
    task['delivery_format'] = 'ppt-task-inline/2'
    task['required_read_files'] = []
    task['contract_query'] = {'tool':'toolbox_project_inspect','action':'contract',
                              'when':'Only if current template/constraints are insufficient; use the current project.'}
    task['source_files'] = [{'file': str(path), 'sha256': digest(path.read_bytes())}
                            for path in (Path(task['packet']), Path(task['response_template']))]
    # Losslessly expose protocol/extension fields omitted by the historical envelope.
    represented = {'task_id','token','kind','target','base_revision','instructions',
                   'context','required_view_files','references','suggested_tools','input_files'}
    task['packet_metadata'] = {k: copy.deepcopy(v) for k,v in packet.items() if k not in represented}
    task['read_instruction'] = ('Current context and response template are complete inline. No packet/template reread is required. '
        'Open must_view_files and any task-specific manuals actually needed; source_files are immutable provenance, not viewing evidence. '
        'If delivery_format is unknown or data is missing, request response_detail=full.')
    return task


def measure_delivery(result):
    """Count only the exact JSON body before adding this accounting record."""
    measured = text_size(result)
    task = result.get('task') or {}
    measured['task'] = text_size(task)
    measured['required_text_file_bytes'] = sum(Path(row['file']).stat().st_size
        for row in task.get('required_read_files', []))
    measured['scope'] = ('Local compact JSON serialization, excluding this record; not wire bytes, model tokens, '
                          'image traffic, or unobserved manual reads.')
    result['delivery_metrics'] = measured
    return result


def production_context(manager, full):
    """Explicit opt-in. Unknown/customized bootstrap text fails open to full context."""
    manifest = manager.root/'assets/context-bootstrap.json'
    if not manifest.is_file():
        return {**full, 'context_profile': 'full', 'profile_fallback': 'bootstrap_manifest_missing'}
    reviewed = json.loads(manifest.read_text(encoding='utf-8'))
    documents = []
    for path, expected in reviewed['sources'].items():
        doc = manager.document(path)
        if doc['customized'] or doc['base_sha256'] != expected:
            return {**full, 'context_profile': 'full', 'profile_fallback': 'bootstrap_changed_or_customized'}
        documents.append({'path':path,'sha256':doc['base_sha256'],'revision':doc['revision'],
                          'tool':'toolbox_manual'})
    result = dict(full)
    # The full current skill, effective policies, instructions, identity, disabled
    # tools and learning consent survive. Only reviewed duplicate startup prose goes.
    result.pop('startup_prompt', None)
    result['context_profile'] = 'production'
    result['bootstrap_documents'] = documents
    result['workflow_defaults'] = {'response_detail':'compact','return_next':True,
        'instruction':'Bind the project, then read current status. Use current inline task context and actual required images. '
                      'Do not replay accepted or unknown submissions. Full context remains available with profile=full.'}
    return measure_delivery(result)
