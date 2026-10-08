"""Data-only transfer and reversible owner edits over the attributed library."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

FORMAT = 'ppt-experience-transfer/1'
EDITABLE = ('title', 'trigger', 'actions', 'verification', 'constraints', 'tags', 'category')
FIELDS = EDITABLE + ('id', 'kind', 'origin', 'evidence', 'tools', 'evidence_level',
                     'runtime_retested_in_this_delivery')
EMPTY = {'sources': [], 'rows': [], 'overrides': {}, 'hidden': {}}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def read_state(external):
    path = Path(external)/'management.sqlite3'
    if not path.exists():
        return copy.deepcopy(EMPTY)
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute('SELECT body FROM state WHERE id=1').fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(EMPTY)


def overlay(sources, rows, external, state=None):
    state = read_state(external) if state is None else state
    sm = {s['source_id']: s for s in sources}
    rm = {r['id']: r for r in rows}
    sm.update({s['source_id']: s for s in state['sources']})
    rm.update({r['id']: r for r in state['rows']})
    for rid, patch in state['overrides'].items():
        if rid in rm:
            rm[rid] = {**rm[rid], **patch, 'user_edited': True}
    return list(sm.values()), [r for rid, r in sorted(rm.items()) if rid not in state['hidden']]


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value))).strip().casefold()


def signature(row):
    # Evidence is merged separately. Different verification/constraints are not exact duplicates.
    return digest({k: sorted(normalize(x) for x in row.get(k, [])) if isinstance(row.get(k), list)
                   else normalize(row.get(k, ''))
                   for k in ('title', 'trigger', 'actions', 'verification', 'constraints', 'tools', 'kind')})


def revision(sources, rows):
    return digest([sources, rows])


def validate_text_fields(row):
    for key in ('title', 'trigger', 'category'):
        if not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > 12000:
            raise ValueError('字段为空或过长 ' + key)
    for key in ('actions', 'verification', 'constraints', 'tags'):
        values = row.get(key)
        if not isinstance(values, list) or len(values) > 100 or (key != 'tags' and not values):
            raise ValueError('需要逐行填写 ' + key)
        if any(not isinstance(v, str) or not v.strip() or len(v) > 12000 for v in values):
            raise ValueError('条目为空或过长 ' + key)


def export_library(root, external, ids=None):
    from .experience_library import load_library, local_file, source_path
    sources, rows, _ = load_library(root, external)
    if ids is not None:
        if not isinstance(ids, list) or not ids or set(ids)-{r['id'] for r in rows}:
            raise ValueError('请选择现有经验')
        rows = [r for r in rows if r['id'] in ids]
    used = {e['source_id'] for r in rows for e in r['evidence']}
    out_sources = []
    for s in sources:
        if s['source_id'] not in used:
            continue
        raw = local_file(s.get('_library_root', root), source_path(s)).read_bytes()
        if hashlib.sha256(raw).hexdigest() != s['sha256']:
            raise ValueError('原文校验失败 ' + s['source_id'])
        out_sources.append({'metadata': {k: v for k, v in s.items() if not k.startswith('_')},
                            'content_base64': base64.b64encode(raw).decode('ascii')})
    entries = [{**{k: r[k] for k in FIELDS if k in r},
                'manual_text': local_file(r.get('_manual_root', root), r['manual']).read_text('utf-8')}
               for r in rows]
    return {'format': FORMAT, 'sources': out_sources, 'entries': entries}


def prepare(payload, root, external):
    from .experience_library import load_library
    if not isinstance(payload, dict) or payload.get('format') != FORMAT:
        raise ValueError('请选择经验库导出的 JSON 文件')
    if len(encoded(payload).encode('utf-8')) > 24_000_000:
        raise ValueError('经验文件超过 24 MB')
    incoming, entries = payload.get('sources'), payload.get('entries')
    if not isinstance(incoming, list) or not isinstance(entries, list) or not 1 <= len(entries) <= 2000 or len(incoming) > 2000:
        raise ValueError('经验文件的来源或条目数量无效')
    sources, rows, tools = load_library(root, external)
    known_tools = {t['id'] for t in tools}
    mapped, source_rows, assets, contents = {}, [], {}, {}
    used_ids = {s['source_id'] for s in sources}
    hashes = {s['sha256']: s['source_id'] for s in sources}
    def allocate(prefix, used):
        n = max([int(x[len(prefix):]) for x in used if re.fullmatch(re.escape(prefix)+r'\d+', x)] or [0])+1
        result = prefix+str(n).zfill(3 if prefix == 'EXP-' else 2)
        used.add(result)
        return result
    for item in incoming:
        meta = item['metadata']
        sid = meta['source_id']
        if not re.fullmatch(r'S\d+', sid) or sid in mapped:
            raise ValueError('来源编号无效或重复')
        raw = base64.b64decode(item['content_base64'], validate=True)
        lines = raw.decode('utf-8').splitlines()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != meta.get('sha256') or len(raw) != meta.get('byte_count') or len(lines) != meta.get('line_count'):
            raise ValueError('来源内容与校验记录不符 ' + sid)
        new_id = hashes.get(sha)
        if not new_id:
            new_id = allocate('S', used_ids)
            hashes[sha] = new_id
            rel = 'sources/'+sha
            source_rows.append({'source_id': new_id, 'topic': str(meta.get('topic', sid)),
                                'relative_path': rel, 'sha256': sha, 'byte_count': len(raw),
                                'line_count': len(lines), 'original_filename': str(meta.get('original_filename', '')),
                                '_library_root': str(Path(external)/'managed-assets')})
            assets['assets/experience/'+rel+'.txt'] = raw
        mapped[sid] = new_id
        contents[sid] = lines
    used_rows = {r['id'] for r in rows}
    seen, added, skipped, evidence_updates = set(), [], [], {}
    signatures = {signature(r): r for r in rows}
    for item in entries:
        if item['id'] in seen or not re.fullmatch(r'EXP-\d{3,}', item['id']):
            raise ValueError('经验编号无效或重复')
        seen.add(item['id'])
        row = {k: copy.deepcopy(item[k]) for k in FIELDS if k in item}
        validate_text_fields(row)
        if row.get('evidence_level') != 'retrospective_only' or row.get('runtime_retested_in_this_delivery') is not False:
            raise ValueError('导入经验不能声明已经通过当前任务验证')
        if not isinstance(row.get('tools'), list) or not row['tools'] or any(t not in known_tools for t in row['tools']):
            raise ValueError('经验引用了当前版本没有的工具')
        if not isinstance(row.get('evidence'), list) or not row['evidence']:
            raise ValueError('经验必须保留原文出处')
        for e in row['evidence']:
            sid, a, b = e['source_id'], e['line_start'], e['line_end']
            if sid not in contents or type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(contents[sid]):
                raise ValueError('出处行号无效')
            if e['excerpt'].strip() != '\n'.join(contents[sid][a-1:b]).strip():
                raise ValueError('出处摘录与原文不符')
            if not isinstance(e.get('reported_state'), str) or not e['reported_state']:
                raise ValueError('出处缺少历史状态')
            e['source_id'] = mapped[sid]
        manual = item.get('manual_text')
        if not isinstance(manual, str) or not manual.strip() or len(manual) > 1_000_000:
            raise ValueError('缺少使用说明或说明过长')
        key = signature(row)
        if key in signatures:
            prior = signatures[key]
            combined = unique(prior['evidence'] + evidence_updates.get(prior['id'], []) + row['evidence'])
            if combined != prior['evidence']:
                evidence_updates[prior['id']] = combined
            skipped.append({'incoming_id': item['id'], 'existing_id': prior['id']})
            continue
        row['id'] = allocate('EXP-', used_rows)
        sha = hashlib.sha256(manual.encode('utf-8')).hexdigest()
        row.update(manual='manuals/'+sha+'.md', _manual_root=str(Path(external)/'managed-assets'), external_import=True)
        assets[row['manual']] = manual.encode('utf-8')
        added.append(row)
        signatures[key] = row
    used_sources = {e['source_id'] for r in added for e in r['evidence']} | {e['source_id'] for es in evidence_updates.values() for e in es}
    source_rows = [s for s in source_rows if s['source_id'] in used_sources]
    return {'revision': revision(sources, rows), 'new_count': len(added), 'duplicate_count': len(skipped),
            'duplicates': skipped, 'evidence_update_count': len(evidence_updates),
            'items': [{'id': r['id'], 'title': r['title']} for r in added],
            '_sources': source_rows, '_rows': added, '_assets': assets, '_updates': evidence_updates}


def unique(items):
    return list({encoded(x): x for x in items}.values())


def call(root, external, action, args):
    from .experience_library import load_library
    external = Path(external)
    sources, rows, _ = load_library(root, external)
    token = revision(sources, rows)
    by_id = {r['id']: r for r in rows}
    if action == 'export':
        return export_library(root, external, args.get('ids'))
    if action == 'import-preview':
        return {k: v for k, v in prepare(args.get('payload'), root, external).items() if not k.startswith('_')}
    if action == 'duplicates':
        pairs = []
        signatures = {r['id']: signature(r) for r in rows}
        for i, a in enumerate(rows):
            for b in rows[i+1:]:
                exact = signatures[a['id']] == signatures[b['id']]
                score = 1.0 if exact else SequenceMatcher(None, normalize(a['title']+' '+a['trigger']), normalize(b['title']+' '+b['trigger']), autojunk=False).ratio()
                if exact or score >= .78:
                    pairs.append({'left': a['id'], 'right': b['id'], 'left_title': a['title'],
                                  'right_title': b['title'], 'exact': exact, 'score': round(score, 3)})
        return {'revision': token, 'pairs': sorted(pairs, key=lambda p: -p['score'])[:200], 'total': len(pairs)}
    if action == 'edit-view':
        row = by_id.get(args.get('id'))
        if not row:
            raise ValueError('经验不存在')
        return {'revision': token, 'row': {k: row.get(k) for k in EDITABLE + ('id', 'evidence')}}
    if action == 'history':
        if not (external/'management.sqlite3').exists():
            return {'revision': token, 'items': []}
        with sqlite3.connect((external/'management.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
            items = [{'id': r[0], 'action': r[1], 'at': r[2], 'summary': r[3]} for r in db.execute(
                'SELECT id,action,at,summary FROM history ORDER BY id DESC LIMIT 50')]
        return {'revision': token, 'items': items}
    if action not in {'import', 'edit', 'merge', 'undo'}:
        raise ValueError('Unknown experience management operation')
    # Validate an import completely before creating any persistent state.
    if action == 'import':
        prepare(args.get('payload'), root, external)
    external.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(external/'management.sqlite3', timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,action TEXT,at TEXT,summary TEXT,before_body TEXT,after_revision TEXT)')
        db.execute('BEGIN IMMEDIATE')
        sources, rows, _ = load_library(root, external)
        if args.get('revision') != revision(sources, rows):
            raise ValueError('经验库已更新，请刷新后重试')
        by_id = {r['id']: r for r in rows}
        state = read_state(external)
        before = encoded(state)
        summary = ''
        if action == 'import':
            plan = prepare(args['payload'], root, external)
            if not plan['_rows'] and not plan['_updates']:
                return {'status': 'unchanged', 'new_count': 0, 'duplicate_count': plan['duplicate_count']}
            for relative, raw in plan['_assets'].items():
                target = external/'managed-assets'/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.read_bytes() != raw:
                        raise ValueError('已归档文件校验失败')
                else:
                    # Immutable content addressed assets become visible only at the DB commit.
                    with target.open('xb') as f:
                        f.write(raw)
            state['sources'].extend(plan['_sources'])
            state['rows'].extend(plan['_rows'])
            for rid, evidence in plan['_updates'].items():
                state['overrides'].setdefault(rid, {})['evidence'] = evidence
            summary = f"导入 {plan['new_count']} 条，跳过 {plan['duplicate_count']} 条重复经验"
        elif action == 'edit':
            rid = args.get('id')
            if rid not in by_id:
                raise ValueError('经验不存在')
            patch = args.get('changes')
            if not isinstance(patch, dict) or not patch or set(patch)-set(EDITABLE):
                raise ValueError('只能编辑方法字段，原文出处不能改写')
            validate_text_fields({**by_id[rid], **patch})
            state['overrides'].setdefault(rid, {}).update(patch)
            summary = '编辑 '+rid
        elif action == 'merge':
            keep, remove = args.get('keep'), args.get('remove')
            if keep == remove or keep not in by_id or remove not in by_id:
                raise ValueError('请选择两条不同的现有经验')
            a, b = by_id[keep], by_id[remove]
            patch = {key: unique(a.get(key, [])+b.get(key, [])) for key in ('actions', 'verification', 'constraints', 'tags', 'tools', 'evidence')}
            if a['trigger'] != b['trigger']:
                patch['trigger'] = a['trigger']+'\n'+b['trigger']
            validate_text_fields({**a, **patch})
            state['overrides'].setdefault(keep, {}).update(patch)
            state['hidden'][remove] = keep
            summary = remove+' 合并到 '+keep+'，保留双方方法与出处'
        else:
            latest = db.execute('SELECT id,before_body,after_revision FROM history ORDER BY id DESC LIMIT 1').fetchone()
            if not latest or args.get('history_id') != latest[0]:
                raise ValueError('只能撤销最近一次修改，请刷新版本记录')
            if latest[2] != token:
                raise ValueError('经验来源在修改后发生变化，不能直接撤销')
            state = json.loads(latest[1])
            summary = '撤销版本 '+str(latest[0])
        db.execute('INSERT OR REPLACE INTO state(id,body) VALUES(1,?)', (encoded(state),))
        # Compute the committed projection without opening a second writer or exposing partial state.
        s, r, _ = load_library(root, external, _management_state=state)
        after_token = revision(s, r)
        db.execute('INSERT INTO history(action,at,summary,before_body,after_revision) VALUES(?,?,?,?,?)',
                   (action, datetime.now(timezone.utc).isoformat(), summary, before, after_token))
        return {'status': 'saved', 'revision': after_token, 'summary': summary}
