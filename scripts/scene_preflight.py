"""Shared, read-only scene import contract and actionable path diagnostics."""
from pathlib import Path
if __package__:
    from .common import read_json, resolve_asset, sha256
    from .validate_scene import validate
else:
    from common import read_json, resolve_asset, sha256
    from validate_scene import validate


def inspect(path, project_root=None):
    path = Path(path).resolve()
    scene = read_json(path)
    if __package__:
        from .scene_paths import prepare
    else:
        from scene_paths import prepare
    try:
        normalized, base, references = prepare(scene, path.parent, project_root)
        errors = validate(normalized, base, project_root=base)
        errors += [r['field']+': '+r['error'] for r in references if 'error' in r]
    except ValueError as exc:
        base, references, errors = path.parent, [], [str(exc)]
    errors = list(dict.fromkeys(errors))
    metadata = scene if isinstance(scene, dict) else {}
    return {'status':'invalid' if errors else 'valid', 'code':'scene_contract_invalid' if errors else None,
            'scene_sha256':sha256(path),'base':str(base),'scene_directory':str(path.parent),
            'path_base':metadata.get('path_base','scene_directory'),
            'project_root':str(base) if metadata.get('version')=='1.1' and references else None,
            'errors':errors,'references':references,
            'mutated':False,'guidance':('Scene 1.1 uses the selected project root; project-contained absolute paths are normalized in memory. '
                if metadata.get('version')=='1.1' else 'Scene 1.0 uses scene-relative paths; moving the scene changes its base. ')+
                'Keep files inside that base. Supply actual evidence; no automatic evidence fabrication.'}


def require(path, project_root=None):
    report = inspect(path, project_root)
    if report['errors']:
        exc = ValueError('Scene import errors: '+'; '.join(report['errors'][:20])+
                         ' | base='+report['base']+' | '+report['guidance'])
        exc.diagnostics = [{'path':r['field'],'code':'scene_reference_invalid',
            'message':r['error'],'base':r['base'],'resolved':r.get('resolved'),
            'value':r['value'],'exists':r.get('exists',False),
            'next_action':report['guidance']} for r in report['references'] if 'error' in r]
        if not exc.diagnostics:
            exc.diagnostics = [{'path':'/scene','code':'scene_contract_invalid','message':message,
                                'next_action':report['guidance']} for message in report['errors']]
        raise exc
    return report
