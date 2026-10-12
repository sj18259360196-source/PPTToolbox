"""Check explicit source transcriptions against native text, not against OCR guesses."""
from common import walk_objects
from workflow_scene import keys, text


def validate_text_checks(result, objects):
    if 'text_checks' not in result:
        return
    checks = result['text_checks']
    if not isinstance(checks, list) or not checks:
        raise ValueError('text_checks must be a nonempty list when supplied')
    inventory = {o['id']: o for o in walk_objects(objects) if o['kind'] == 'text'}
    seen = set()
    from validation_checks import Checks
    findings=Checks()
    for index,row in enumerate(checks):
        try:keys(row, ['object_id', 'source_text'])
        except ValueError as exc:
            findings.add(str(exc),'/'+str(index),'transcription_fields');continue
        oid = text(row['object_id'], 'object_id')
        text(row['source_text'], 'source_text', empty=True)
        if oid not in inventory or oid in seen:
            findings.add('text_checks requires unique current text object IDs: ' + oid,
                         '/'+str(index)+'/object_id','transcription_target',oid)
            continue
        seen.add(oid)
        obj = inventory[oid]
        if 'paragraphs' in obj:
            actual = '\n'.join(''.join(r['text'] for r in p['runs']) for p in obj['paragraphs'])
        elif 'runs' in obj:
            actual = ''.join(r['text'] for r in obj['runs'])
        else:
            actual = obj.get('text', '')
        # Preserve punctuation, whitespace, digits and units. No fuzzy acceptance.
        if actual != row['source_text'] and result['status'] == 'passed':
            findings.add('Source text differs; use needs_changes or blocked: '+oid,
                         '/'+str(index)+'/source_text','source_text_mismatch',oid)
    findings.finish()
