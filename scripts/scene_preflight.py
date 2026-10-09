"""Shared, read-only scene import contract and actionable path diagnostics."""
from pathlib import Path
if __package__:
    from .common import read_json, resolve_asset, sha256
    from .validate_scene import validate
else:
    from common import read_json, resolve_asset, sha256
    from validate_scene import validate


def inspect(path):
    path = Path(path).resolve()
    scene = read_json(path)
    errors = validate(scene, path.parent)
    references = []
    def scan(value, pointer=''):
        if isinstance(value, dict):
            for key, item in value.items():
                field = pointer+'/'+key
                if key in {'reference','asset'} and isinstance(item, str):
                    record = {'field': field, 'value': item, 'base': str(path.parent)}
                    try:
                        resolved = resolve_asset(path.parent, item)
                        record.update(resolved=str(resolved), exists=resolved.is_file())
                        if not resolved.is_file():
                            errors.append(field+': missing file relative to scene directory: '+item)
                    except (OSError, ValueError) as exc:
                        record.update(exists=False, error=str(exc))
                        errors.append(field+': '+str(exc))
                    references.append(record)
                elif isinstance(item, (dict,list)): scan(item, field)
        elif isinstance(value, list):
            for index, item in enumerate(value): scan(item, pointer+'/'+str(index))
    scan(scene)
    errors = list(dict.fromkeys(errors))
    return {'status':'invalid' if errors else 'valid', 'code':'scene_contract_invalid' if errors else None,
            'scene_sha256':sha256(path),'base':str(path.parent),'errors':errors,'references':references,
            'mutated':False,'guidance':'Use scene-relative paths for reference/asset; keep references inside that base. Supply real evidence for every required object; no automatic evidence fabrication.'}


def require(path):
    report = inspect(path)
    if report['errors']:
        raise ValueError('Scene import errors: '+'; '.join(report['errors'][:20])+
                         ' | base='+report['base']+' | '+report['guidance'])
    return report
