"""Curate reusable default methods without publishing private source records."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

SOURCE_ID = 'S38'

def entries(root):
    rows=[json.loads(line) for line in (Path(root)/'assets/experience/knowledge/experience-ledger.jsonl').read_text('utf-8').splitlines() if line.strip()]
    ids=[r['id'] for r in rows]
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('Default experience requires nonempty unique IDs')
    return sorted(rows,key=lambda r:int(r['id'].split('-')[1]))

def build(root: Path):
    """Maintainer build step; never called to ingest arbitrary runtime content."""
    root = Path(root)
    original = entries(root)
    by_id = {row['id']:row for row in original}
    default_ids=list(by_id)
    from distribution.public_source import public_text
    def normalize(value):
        if isinstance(value,str): return public_text(value)
        if isinstance(value,list): return [normalize(v) for v in value]
        if isinstance(value,dict): return {k:normalize(v) for k,v in value.items()}
        return value
    lines = ['# PPT Toolbox 项目默认方法',
             '随包提供的通用方法说明。只保留适用条件、操作、验证和限制，不包含个人项目原文、图片或历史验收结论。',
             '本说明属于维护者整理的方法文档。当前任务仍需核对合同、授权与实际输出。']
    rows = []
    for key in default_ids:
        old = by_id[key]
        row = {field:old[field] for field in
               ('id','category','title','kind','trigger','actions','verification','constraints','tags','manual','tools')}
        additions={
            'EXP-181':'参数输入可用 graphics_construct；先 graphics_inspect 核对当前合同，再预览与授权编译。',
            'EXP-186':'graphics_read_properties 在独立副本读回有效色标 alpha；混合透明度为 unknown，不能推算成全局 alpha。',
            'EXP-188':'graphics_boolean_trials 预检并生成独立 rebuild_patch 请求；补当前 context_id 后执行，不自动采用或增加预算。',
            'EXP-189':'graphics_compare_contours 使用同尺度局部和显式二值掩膜；原始距离与质心位移估计分别保留。',
            'EXP-190':'受限节点与控制点修改使用 rebuild_patch native.nodes；检查 expected 坐标、位移上限、保存重开、孔洞和保护对象，再看新 Office 渲染。'}
        if key in additions:row['actions']=[*row['actions'],additions[key]]
        row=normalize(row)
        row['method_provenance']={'source_ids':sorted({e['source_id'] for e in old.get('evidence',[])}),
                                 'original_evidence_level':old.get('evidence_level','retrospective_only'),
                                 'scope':'Method summary; source documents and past acceptance are not bundled'}
        lines.append('## '+row['id']+' '+row['title'])
        # No historic excerpt, machine path, artifact identity or acceptance record.
        excerpt = '；'.join(row['actions'])
        lines.append(excerpt)
        row.update(origin='bundled_method_guidance',evidence_level='retrospective_only',
                   runtime_retested_in_this_delivery=False,
                   evidence=[dict(source_id=SOURCE_ID,line_start=len(lines),line_end=len(lines),
                                  excerpt=excerpt,reported_state='documented_method')])
        rows.append(row)
    out = root/'assets/experience/defaults'
    (out/'sources').mkdir(parents=True,exist_ok=True)
    (out/'knowledge').mkdir(exist_ok=True)
    source = out/'sources/S38_原生绘图基础方法.md.txt'
    source.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    metadata = dict(source_id=SOURCE_ID,original_filename=source.name,
                    topic='项目全部默认方法',relative_path='sources/S38_原生绘图基础方法.md',
                    title='PPT Toolbox 项目默认方法',document_type='bundled_method_guidance',
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),byte_count=source.stat().st_size,
                    line_count=len(lines),primary_artifacts_in_this_package=False,
                    line_numbering='physical_1_based_in_archived_source',
                    independent_case_identity='builtin-native-graphics-methods',lineage_group='builtin-native-graphics-methods')
    (out/'knowledge/sources.json').write_text(json.dumps([metadata],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'knowledge/experience-ledger.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
    return {'source_id':SOURCE_ID,'experience_ids':default_ids,'count':len(rows)}

def install_defaults(root: Path, output: Path):
    """Copy only the reviewed, explicit method bundle into a public export."""
    import shutil
    source = Path(root)/'assets/experience/defaults'
    if (Path(root)/'PUBLIC_DISTRIBUTION.json').exists():source=Path(root)/'assets/experience'
    target = Path(output)/'assets/experience'
    selected=['knowledge/sources.json','knowledge/experience-ledger.jsonl','sources/S38_原生绘图基础方法.md.txt']
    for path in [source/name for name in selected]:
        if path.is_file():
            if path.is_symlink(): raise ValueError('Linked default source')
            dest=target/path.relative_to(source)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)
    rows=[json.loads(line) for line in (target/'knowledge/experience-ledger.jsonl').read_text('utf-8').splitlines() if line.strip()]
    if [row['id'] for row in rows] != [row['id'] for row in entries(root)]:
        raise ValueError('Unexpected public default IDs')
    return len(rows)

if __name__=='__main__':
    print(json.dumps(build(Path(__file__).resolve().parents[1]),ensure_ascii=False))
