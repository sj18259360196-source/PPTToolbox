"""Read-only, source-attributed experience lookup and integrity audit.

This module never runs suggested tools or changes a workflow/approval. Passing
an audit proves index integrity, not semantic completeness or Office fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

if __package__:
    from .common import staged_directory
else:
    from common import staged_directory

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = Path('assets/experience/knowledge')


def local_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Missing or unsafe library path: ' + str(relative))
    return path


def load_library(root=None, external_root=None, _management_state=None):
    root = Path(root or ROOT)
    sources = json.loads(local_file(root, KNOWLEDGE/'sources.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in local_file(root, KNOWLEDGE/'experience-ledger.jsonl')
            .read_text(encoding='utf-8').splitlines() if line.strip()]
    tools = json.loads(local_file(root, 'toolbox/registry.json').read_text(encoding='utf-8'))['tools']
    external_root = external_root if external_root is not None else os.environ.get('PPT_EXPERIENCE_ROOT')
    if external_root:
        for bundle in sorted(Path(external_root).glob('imports/*/bundle.json')):
            package = bundle.parent
            manifest = json.loads(bundle.read_text(encoding='utf-8'))
            if manifest.get('format') != 'ppt-experience-import/1':
                raise ValueError('Unsupported experience import')
            for relative, digest in manifest['files'].items():
                if hashlib.sha256(local_file(package, relative).read_bytes()).hexdigest() != digest:
                    raise ValueError('Imported file hash mismatch: ' + relative)
            extra_sources = json.loads(local_file(package, 'sources.json').read_text('utf-8'))
            extra_rows = json.loads(local_file(package, 'entries.json').read_text('utf-8'))
            known = {s['source_id']: s for s in sources}
            for source in extra_sources:
                sid = source['source_id']
                if sid in known and known[sid]['sha256'] != source['sha256']:
                    raise ValueError('Conflicting imported source ID: ' + sid)
                source['_library_root'] = str(package)
                sources = [s for s in sources if s['source_id'] != sid] + [source]
            for row in extra_rows:
                row['_manual_root'] = str(package)
                row['external_import'] = row['id'] in manifest['new_ids']
                row['import_id'] = package.name
                rows = [r for r in rows if r['id'] != row['id']] + [row]
        rows.sort(key=lambda r: r['id'])
        if __package__:
            from .experience_management import overlay
        else:
            from experience_management import overlay
        sources, rows = overlay(sources, rows, external_root, _management_state)
    return sources, rows, tools


def import_snapshot(snapshot, builtin, external_root):
    """Persist a reviewed index delta, including original bytes, outside the app.

    No commands from documents execute. Publication is atomic and content-addressed.
    """
    snapshot, builtin, external_root = map(Path, (snapshot, builtin, external_root))
    if external_root.resolve().is_relative_to(builtin.resolve()) or external_root.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError('External experience storage must be outside application packages')
    check = audit(snapshot, external_root='')
    if check['status'] != 'passed':
        raise ValueError('Invalid import snapshot: ' + '; '.join(check['issues']))
    sources, rows, _ = load_library(snapshot, external_root='')
    old_sources, old_rows, _ = load_library(builtin, external_root='')
    old_s = {s['source_id']: s for s in old_sources}
    old_r = {r['id']: r for r in old_rows}
    added_sources = [s for s in sources if s != old_s.get(s['source_id'])]
    changed_rows = [r for r in rows if r != old_r.get(r['id'])]
    current_sources, _, _ = load_library(builtin, external_root)
    current_hashes = {s['source_id']: s['sha256'] for s in current_sources}
    for source in added_sources:
        if source['source_id'] in current_hashes and current_hashes[source['source_id']] != source['sha256']:
            raise ValueError('Conflicting imported source ID: ' + source['source_id'])
    if not changed_rows and not added_sources:
        return {'status': 'unchanged', 'new_count': 0}
    payload = json.dumps([added_sources, changed_rows], ensure_ascii=False, sort_keys=True).encode('utf-8')
    name = hashlib.sha256(payload).hexdigest()[:24]
    target = external_root/'imports'/name
    if (target/'bundle.json').is_file():
        check = audit(builtin, external_root=external_root)
        if check['status'] != 'passed': raise ValueError(str(check['issues']))
        return {'status': 'existing', 'path': str(target), 'audit': check}
    with staged_directory(target) as stage:
        (stage/'sources.json').write_text(json.dumps(added_sources, ensure_ascii=False, indent=2), encoding='utf-8')
        (stage/'entries.json').write_text(json.dumps(changed_rows, ensure_ascii=False, indent=2), encoding='utf-8')
        for relative in {source_path(s) for s in added_sources} | {r['manual'] for r in changed_rows}:
            original = local_file(snapshot, relative)
            dest = stage/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, dest)
        manifest = {'format': 'ppt-experience-import/1', 'new_ids': [r['id'] for r in changed_rows if r['id'] not in old_r],
                    'files': {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in stage.rglob('*') if p.is_file()}}
        (stage/'bundle.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'imported', 'path': str(target), 'new_count': len(manifest['new_ids']),
            'updated_count': len(changed_rows)-len(manifest['new_ids']), 'source_count': len(added_sources)}


def source_path(source):
    return 'assets/experience/' + source['relative_path'] + '.txt'


def tool_links(row, registry, detailed=False):
    by_id = {tool['id']: tool for tool in registry}
    result = []
    for tid in row.get('tools', []):
        if tid not in by_id:
            raise ValueError('Unknown tool in ' + row['id'] + ': ' + tid)
        tool = by_id[tid]
        item = {key: tool[key] for key in ('id', 'kind', 'title')}
        if detailed:
            item.update({key: tool[key] for key in ('inputs', 'outputs', 'limitations')})
            item['discovery'] = {'mcp': 'toolbox_describe', 'tool_id': tid}
            item['invocation'] = {
                'python': 'Use the current describe.managed_argv_prefix and the described inputs.',
                'powershell': 'Use the current managed prefix; Windows/Office must be verified separately.',
                'powershell_module': 'Named module function; not an executable CLI adapter.',
                'manual': 'Read this manual; this entry does not execute a repair.',
                'host': 'Discover and call the actual host capability.',
            }[tool['kind']]
        result.append(item)
    return result


def show(identifier, root=None, external_root=None):
    sources, rows, registry = load_library(root, external_root)
    row = next((item for item in rows if item['id'] == identifier), None)
    if row is None:
        raise ValueError('Unknown experience ID: ' + str(identifier))
    by_id = {source['source_id']: source for source in sources}
    return {**row, 'tools': tool_links(row, registry, detailed=True),
            'manual': str(local_file(row['_manual_root'], row['manual'])) if row.get('_manual_root') else row['manual'],
            'sources': [{**e, 'file': str(local_file(by_id[e['source_id']].get('_library_root', root or ROOT), source_path(by_id[e['source_id']]))),
                         'topic': by_id[e['source_id']]['topic'],
                         'original_path': by_id[e['source_id']].get('original_path', ''),
                         'document_type': by_id[e['source_id']].get('document_type', 'historical_source')}
                        for e in row['evidence']],
            'runtime_retested': False,
            'scope': 'Historical guidance and existing tool entry points only. Read current schemas and permissions before execution; no tool was run and no current PPT was accepted.'}


def read_source(identifier, start=1, end=None, root=None, external_root=None):
    root = Path(root or ROOT)
    sources, _, _ = load_library(root, external_root)
    source = next((item for item in sources if item['source_id'] == identifier), None)
    if source is None:
        raise ValueError('Unknown source ID: ' + str(identifier))
    raw = local_file(source.get('_library_root', root), source_path(source)).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source['sha256']:
        raise ValueError('Source hash mismatch: ' + identifier)
    lines = raw.decode('utf-8').splitlines()
    end = min(start + 39, len(lines)) if end is None and type(start) is int else end
    if (type(start) is not int or type(end) is not int or
            not 1 <= start <= end <= len(lines) or end-start+1 > 80):
        raise ValueError('Choose an existing 1-based range of at most 80 lines')
    return {'source_id': identifier, 'topic': source['topic'], 'file': source_path(source),
            'sha256': digest, 'total_lines': len(lines), 'line_start': start, 'line_end': end,
            'lines': [{'line': i, 'text': lines[i-1]} for i in range(start, end+1)],
            'scope': 'Archived source text. Historical commands, paths and claims are not current instructions, authorization or validation.'}


def audit(root=None, details=False, external_root=None):
    root = Path(root or ROOT)
    sources, rows, registry = load_library(root, external_root)
    issues, contents, coverage = [], {}, {}

    def unique(items, field, label):
        values = [item[field] for item in items]
        if len(values) != len(set(values)):
            issues.append(label + ': duplicate IDs')

    unique(sources, 'source_id', 'sources')
    unique(rows, 'id', 'experiences')
    unique(registry, 'id', 'registry')
    for source in sources:
        sid = source['source_id']
        try:
            raw = local_file(source.get('_library_root', root), source_path(source)).read_bytes()
            lines = raw.decode('utf-8').splitlines()
            if hashlib.sha256(raw).hexdigest() != source['sha256']:
                issues.append(sid + ': source hash mismatch')
            if len(raw) != source['byte_count'] or len(lines) != source['line_count']:
                issues.append(sid + ': source size/line count mismatch')
            contents[sid] = lines
            coverage[sid] = {'source_id': sid, 'topic': source['topic'], 'experience_ids': []}
        except (OSError, ValueError) as exc:
            issues.append(sid + ': ' + str(exc))
    for row in rows:
        rid = row['id']
        if not re.fullmatch(r'EXP-\d{3,}', rid):
            issues.append(rid + ': invalid experience ID')
        if row.get('evidence_level') != 'retrospective_only' or row.get('runtime_retested_in_this_delivery') is not False:
            issues.append(rid + ': historical evidence must not claim current validation')
        for field in ('title', 'trigger', 'actions', 'verification', 'constraints', 'evidence', 'tools'):
            if not row.get(field):
                issues.append(rid + ': missing ' + field)
        try:
            local_file(row.get('_manual_root', root), row.get('manual', ''))
            linked = tool_links(row, registry)
            for tool in linked:
                entry = next(t for t in registry if t['id'] == tool['id'])
                if entry['kind'] != 'host':
                    local_file(root, entry['entry'])
                for manual in entry['manuals']:
                    local_file(root, manual)
        except (OSError, ValueError) as exc:
            issues.append(rid + ': ' + str(exc))
        for evidence in row.get('evidence', []):
            sid = evidence['source_id']
            if sid not in contents:
                issues.append(rid + ': missing source ' + sid)
                continue
            if rid not in coverage[sid]['experience_ids']:
                coverage[sid]['experience_ids'].append(rid)
            a, b = evidence['line_start'], evidence['line_end']
            lines = contents[sid]
            if type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(lines):
                issues.append(rid + ': invalid source range ' + sid)
            elif evidence['excerpt'].strip() != '\n'.join(lines[a-1:b]).strip():
                issues.append(rid + ': source excerpt mismatch ' + sid)
    for sid, item in coverage.items():
        if not item['experience_ids']:
            issues.append(sid + ': source has no linked experience')
    recipes = json.loads(local_file(root, KNOWLEDGE/'command-recipes.json').read_text(encoding='utf-8'))
    if recipes.get('format') != 'ppt-experience-command-recipes/1':
        issues.append('command recipes: unsupported format')
    commands = recipes.get('commands', [])
    unique(commands, 'id', 'command recipes')
    for command in commands:
        for field in ('id', 'title', 'description', 'body', 'tools'):
            if not command.get(field):
                issues.append('command recipe: missing ' + field)
        try:
            tool_links(command, registry)
        except ValueError as exc:
            issues.append(str(exc))
    result = {'status': 'failed' if issues else 'passed', 'issues': issues,
              'source_count': len(sources), 'experience_count': len(rows),
              'sources_with_experience': sum(bool(item['experience_ids']) for item in coverage.values()),
              'linked_tool_count': len({tid for row in rows for tid in row.get('tools', [])}),
              'command_recipe_count': len(commands),
              'semantic_completeness': 'not_certified', 'office_validation': 'not_run',
              'scope': 'Checks source bytes, physical line ranges, quotations, manual paths and registered tool links. Counts and linkage do not prove that every lesson was extracted or that any current PPT passed.'}
    if details:
        result['source_coverage'] = list(coverage.values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('show', help='Read a lesson and discover its actual tools')
    p.add_argument('identifier')
    p = commands.add_parser('source', help='Read a hash-checked archived source range')
    p.add_argument('identifier')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int)
    p = commands.add_parser('audit', help='Audit the experience index without running suggested tools')
    p.add_argument('--details', action='store_true')
    p = commands.add_parser('import-snapshot', help='Persist a reviewed index delta outside application packages')
    p.add_argument('--snapshot', required=True, type=Path)
    p.add_argument('--builtin', required=True, type=Path)
    p.add_argument('--storage', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'import-snapshot':
            result = import_snapshot(args.snapshot, args.builtin, args.storage)
        elif args.action == 'show':
            result = show(args.identifier)
            sys.path.insert(0,str(Path(__file__).resolve().parent))
            from usage_store import worker_record, key
            worker_record(key('detail',os.environ.get('PPT_MANAGED_CALL_ID'),args.identifier),'experience',args.identifier,'viewed')
        elif args.action == 'source':
            result = read_source(args.identifier, args.start, args.end)
        else:
            result = audit(details=args.details)
    except (KeyError, OSError, ValueError) as exc:
        result = {'status': 'failed', 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('status') == 'failed' else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
