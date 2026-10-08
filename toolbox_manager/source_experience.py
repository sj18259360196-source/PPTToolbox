"""Read-only UI access to bundled knowledge plus persistent user imports."""
import json
import re
from scripts.experience_library import load_library, show, read_source


def call(manager, action, args):
    options = {'root': manager.root, 'external_root': manager.data/'experience-library'}
    if action == 'list':
        sources, rows, _ = load_library(**options)
        query = str(args.get('query', '')).casefold().split()
        items = []
        for row in rows:
            item = {k: v for k, v in row.items() if not k.startswith('_') and k != 'evidence'}
            item['source_ids'] = list(dict.fromkeys(e['source_id'] for e in row['evidence']))
            item['proposed'] = row.get('kind') == 'proposed_method'
            item['external_import'] = bool(row.get('external_import'))
            if all(word in json.dumps(item, ensure_ascii=False).casefold() for word in query):
                items.append(item)
        return {'items': items, 'total': len(rows), 'source_count': len(sources),
                'imported_count': sum(bool(r.get('external_import')) for r in rows),
                'storage_path': str(options['external_root'])}
    if action == 'show':
        result = show(args.get('id'), **options)
        result = {k: v for k, v in result.items() if not k.startswith('_')}
        result['failure_records'] = [e for e in result['sources']
                                     if re.search(r'失败|接缝|问题|错误|不足|失真|丢失|误导', e['excerpt'])]
        return result
    if action == 'source':
        return read_source(args.get('id'), int(args.get('start', 1)),
                           int(args['end']) if args.get('end') else None, **options)
    raise ValueError('Unknown source experience operation')
