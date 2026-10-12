"""Bind explicit image-text observations to generated assets; never OCR or certify."""
from pathlib import Path

if __package__:
    from .common import resolve_asset, sha256, walk_objects
else:
    from common import resolve_asset, sha256, walk_objects

CHECK_SCHEMA = {'type': 'array', 'minItems': 1, 'items': {
    'type': 'object', 'additionalProperties': False,
    'required': ['object_id', 'asset_sha256', 'observed_text'],
    'properties': {'object_id': {'type': 'string', 'minLength': 1},
                   'asset_sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
                   'observed_text': {'type': 'array', 'items': {'type': 'string'}}}}}


def requirements(objects, project):
    rows = []
    for obj in walk_objects(objects):
        if obj['kind'] != 'image' or obj.get('source_kind') != 'generated':
            continue
        decision = obj.get('generation_decision') or {}
        expected = [r['text'] for r in decision.get('embedded_text', []) if r['legibility'] == 'readable']
        if not expected:
            continue
        path = resolve_asset(Path(project), obj['asset'])
        rows.append({'object_id': obj['id'], 'asset': obj['asset'],
                     'asset_sha256': sha256(path), 'expected_text': expected,
                     'text_ownership': decision.get('text_ownership')})
    return rows


def validate(result, objects, project):
    import jsonschema
    required = {r['object_id']: r for r in requirements(objects, project)}
    supplied = result.get('material_text_checks', [])
    if 'material_text_checks' in result:
        errors=list(jsonschema.Draft202012Validator(CHECK_SCHEMA).iter_errors(supplied))
        if errors:raise ValueError('material_text_checks: '+errors[0].message)
    seen = set()
    viewed = {(Path(p) if Path(p).is_absolute() else Path(project)/p).resolve()
              for p in result['viewed_files']}
    for row in supplied:
        oid = row['object_id']
        if oid not in required or oid in seen:
            raise ValueError('material_text_checks requires unique current generated image IDs')
        seen.add(oid)
        expected = required[oid]
        if row['asset_sha256'] != expected['asset_sha256']:
            raise ValueError('Material text observation belongs to different image bytes')
        if resolve_asset(Path(project), expected['asset']).resolve() not in viewed:
            raise ValueError('Material text check requires viewing the actual generated image')
        if row['observed_text'] != expected['expected_text'] and result['status'] == 'passed':
            raise ValueError('Generated material text differs; use needs_changes or blocked')
    if result['status'] == 'passed' and seen != set(required):
        raise ValueError('Passing source review requires exact material_text_checks for generated image text')
