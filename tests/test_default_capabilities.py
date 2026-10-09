"""Every project method becomes a default; no machine history is required."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from distribution.builtin_experience import build,entries,install_defaults

def test_all_methods_and_future_additions_are_default(tmp_path):
    root=tmp_path/'source';p=root/'assets/experience/knowledge/experience-ledger.jsonl'
    p.parent.mkdir(parents=True)
    original=entries(ROOT)
    extra={**original[-1],'id':'EXP-9999','title':'Future method','actions':['Use current contracts']}
    p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in [*original,extra]),encoding='utf-8')
    result=build(root)
    assert set(result['experience_ids'])=={r['id'] for r in original}|{'EXP-9999'}
    output=tmp_path/'export';count=install_defaults(root,output)
    assert count==len(original)+1
    rows=entries(output)
    assert all(r['origin']=='bundled_method_guidance' for r in rows)
    assert all(r['runtime_retested_in_this_delivery'] is False for r in rows)

def test_default_bundle_matches_full_catalog():
    source=ROOT if (ROOT/'PUBLIC_DISTRIBUTION.json').exists() else ROOT/'assets/experience/defaults'
    p=source/'assets/experience/knowledge/experience-ledger.jsonl' if source==ROOT else source/'knowledge/experience-ledger.jsonl'
    defaults=[json.loads(l) for l in p.read_text('utf-8').splitlines() if l.strip()]
    assert {r['id'] for r in defaults}=={r['id'] for r in entries(ROOT)}

def test_stale_subset_is_rejected(tmp_path):
    import pytest
    p=tmp_path/'assets/experience/knowledge/experience-ledger.jsonl';p.parent.mkdir(parents=True)
    rows=entries(ROOT)[:2];p.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    build(tmp_path)
    defaults=tmp_path/'assets/experience/defaults/knowledge/experience-ledger.jsonl'
    defaults.write_text(defaults.read_text('utf-8').splitlines()[0]+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='Unexpected'):install_defaults(tmp_path,tmp_path/'out')
