"""Phase-1 regressions. All Office receipts here are explicitly synthetic fixtures.
They test rejection of inconsistent evidence, not real Office rendering or visual quality.
"""
from __future__ import annotations
import copy
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from test_tools import ROOT, synthetic_receipts
from common import read_json, write_json, sha256
from compare_images import compare
from compare_deck import compare_deck
from inspect_pptx import inspect
from build_pptx import build
from validate_scene import validate
from verify_delivery import verify
from evidence_contract import (required_review, normalize_regions, reference_snapshot,
                               validate_render, validate_local_coverage, regions_by_index)
from package_skill import package, verify_archive, validate_local_links


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp('phase1-synthetic')
    shutil.copyfile(ROOT/'examples/sample-alpha.png',root/'sample-alpha.png')
    scene=root/'scene.json'; write_json(scene,read_json(ROOT/'examples/three-page-scene.json'))
    pptx=root/'candidate.pptx';build(scene,pptx)
    audit=root/'audit.json';r=inspect(pptx,scene);write_json(audit,r)
    synthetic_receipts((pptx,audit,scene,r),root)
    return root


@pytest.fixture
def evidence(seed,tmp_path):
    root=tmp_path/'case';shutil.copytree(seed,root)
    return root


def gate(root):
    return verify(root/'candidate.pptx',root/'audit.json',root/'fake-office.json',
                  root/'fake-review.json',root/'fake-comparisons/deck-comparison.json',root/'scene.json')


def comp_paths(root):
    path=root/'fake-comparisons/deck-comparison.json';return path,read_json(path)


def resign_test_comparison(root,comp):
    """Update dependent hashes in TEST fixtures to isolate the intended defect."""
    path=root/'fake-comparisons/deck-comparison.json';write_json(path,comp)
    review=root/'fake-review.json';r=read_json(review);r['comparison_sha256']=sha256(path);write_json(review,r)


@pytest.mark.parametrize('name',['full','FULL','Full','comparison','deck-comparison','README'])
def test_reserved_ids_rejected_before_any_output(tmp_path,name):
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p);out=tmp_path/'cmp'
    with pytest.raises(ValueError,match='Reserved'):
        compare(p,p,out,[{'id':name,'bbox':[0,0,10,10]}])
    assert not out.exists()


@pytest.mark.parametrize('names',[['part','part'],['part','PART']])
def test_duplicate_ids_rejected_before_writing(tmp_path,names):
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p)
    with pytest.raises(ValueError,match='duplicate'):
        compare(p,p,tmp_path/'cmp',[{'id':n,'bbox':[0,0,10,10]} for n in names])
    assert not (tmp_path/'cmp').exists()


@pytest.mark.parametrize('box',[[False,0,10,10],[0.0,0,10,10],[0,0,0,10],[-1,0,10,10],
                              [0,0,41,10],[0,0,10,25],[0,0,10],None])
def test_all_region_coordinates_checked_before_output(tmp_path,box):
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p)
    with pytest.raises(ValueError):
        compare(p,p,tmp_path/'cmp',[{'id':'good','bbox':[0,0,5,5]},{'id':'bad','bbox':box}])
    assert not (tmp_path/'cmp').exists()


@pytest.mark.parametrize('scale',[0,-1,9,1.5,True])
def test_invalid_display_scale_rejected(tmp_path,scale):
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p)
    with pytest.raises(ValueError):compare(p,p,tmp_path/'cmp',region_scale=scale)
    assert not (tmp_path/'cmp').exists()


@pytest.mark.parametrize('name',['../part','/tmp/x',r'C:\x','区域','a'*81,'part.png'])
def test_unsafe_region_ids(tmp_path,name):
    with pytest.raises(ValueError):normalize_regions([{'id':name,'bbox':[0,0,3,3]}],[10,10])


def test_existing_comparison_cannot_be_overwritten(tmp_path):
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p)
    out=tmp_path/'cmp';compare(p,p,out);before=sha256(out/'comparison.json')
    with pytest.raises(FileExistsError):compare(p,p,out)
    assert sha256(out/'comparison.json')==before


def test_failure_does_not_publish_passed_or_partial_images(tmp_path,monkeypatch):
    import compare_images
    p=tmp_path/'a.png';Image.new('RGB',(40,24)).save(p);real=compare_images._labelled_side
    def fail(a,b,**kwargs):
        if a.width==10:raise OSError('Synthetic write failure on local region')
        return real(a,b,**kwargs)
    monkeypatch.setattr(compare_images,'_labelled_side',fail)
    with pytest.raises(OSError):compare(p,p,tmp_path/'cmp',[{'id':'part','bbox':[0,0,10,10]}])
    assert not (tmp_path/'cmp').exists()
    assert not list(tmp_path.glob('.cmp.staging-*'))


@pytest.mark.parametrize('field', ['sha256','width','height','file_missing','file_traversal','file_absolute',
                                  'file_windows','index_duplicate','index_string','index_bool','index_extra','not_png'])
def test_compare_deck_rejects_bad_render_before_publishing(evidence,field):
    rp=evidence/'fake-office.json';r=read_json(rp);first=r['slides'][0]
    if field=='sha256':first['sha256']='0'*64
    elif field in {'width','height'}:first[field]+=1
    elif field=='file_missing':first['file']='missing.png'
    elif field=='file_traversal':first['file']='../outside.png'
    elif field=='file_absolute':first['file']=str((evidence/first['file']).resolve())
    elif field=='file_windows':first['file']=r'C:\fake.png'
    elif field=='index_duplicate':r['slides'][1]['index']=1
    elif field=='index_string':first['index']='1'
    elif field=='index_bool':first['index']=True
    elif field=='index_extra':first['index']=4
    elif field=='not_png':
        p=evidence/first['file'];Image.new('RGB',(960,540)).save(p,format='JPEG');first['sha256']=sha256(p)
    write_json(rp,r)
    with pytest.raises((ValueError,FileNotFoundError)):
        compare_deck(evidence/'scene.json',rp,evidence/'newcmp',evidence/'fake-regions.json',pptx_path=evidence/'candidate.pptx')
    assert not (evidence/'newcmp').exists()


def test_compare_deck_requires_actual_candidate(evidence):
    with pytest.raises(ValueError,match='actual candidate'):
        compare_deck(evidence/'scene.json',evidence/'fake-office.json',evidence/'newcmp')


def test_wrong_pptx_identity_rejected(evidence):
    p=evidence/'other.pptx';p.write_bytes(b'OTHER FILE')
    with pytest.raises(ValueError,match='different PPTX'):
        compare_deck(evidence/'scene.json',evidence/'fake-office.json',evidence/'newcmp',evidence/'fake-regions.json',pptx_path=p)


@pytest.mark.parametrize('bad',[
    {'slides':[{'index':1,'regions':[]},{'index':1,'regions':[]}]},
    {'slides':[{'index':True,'regions':[]}]},
    {'slides':[{'index':4,'regions':[]}]},
    {'slides':[{'index':'1','regions':[]}]},
    {'slides':[{'index':1,'regionz':[]}]},[],{'slides':[],'silent_extra':1}])
def test_deck_region_spec_rejects_ambiguous_or_out_of_range(bad):
    with pytest.raises(ValueError):regions_by_index(bad,3)


def test_last_page_invalid_does_not_publish_earlier_pages(evidence):
    p=evidence/'fake-regions.json';r=read_json(p);r['slides'][-1]['regions'][0]['id']='full';write_json(p,r)
    with pytest.raises(ValueError):compare_deck(evidence/'scene.json',evidence/'fake-office.json',evidence/'newcmp',p,pptx_path=evidence/'candidate.pptx')
    assert not (evidence/'newcmp').exists()


@pytest.mark.parametrize('oid',['p01.asset','p02.table','p02.chart','p03.half','p03.edge'])
def test_each_structurally_mandatory_object_needs_local_evidence(evidence,oid):
    p=evidence/'fake-regions.json';r=read_json(p)
    for slide in r['slides']:slide['regions']=[x for x in slide['regions'] if oid not in x['object_ids']]
    write_json(p,r)
    with pytest.raises(ValueError,match='Missing mandatory'):
        compare_deck(evidence/'scene.json',evidence/'fake-office.json',evidence/'newcmp',p,pptx_path=evidence/'candidate.pptx')
    assert not (evidence/'newcmp').exists()


def test_tiny_crop_cannot_claim_to_cover_big_object(evidence):
    p=evidence/'fake-regions.json';r=read_json(p);r['slides'][1]['regions'][0]['bbox']=[0,0,4,4];write_json(p,r)
    with pytest.raises(ValueError,match='does not cover'):
        compare_deck(evidence/'scene.json',evidence/'fake-office.json',evidence/'newcmp',p,pptx_path=evidence/'candidate.pptx')


def test_explicit_user_required_object_is_additive(evidence):
    p=evidence/'scene.json';s=read_json(p);s['slides'][0]['review_requirements']={'local_objects':['p01.title']}
    assert validate(s,p.parent)==[]
    req=required_review(s['slides'][0]);assert 'p01.title' in req['local_objects'];assert 'p01.asset' in req['local_objects']
    s['slides'][0]['review_requirements']['local_objects']=['nonexistent']
    assert validate(s,p.parent)


def test_generated_asset_does_not_need_magic_role_to_trigger():
    slide={'objects':[{'id':'img','kind':'image','source_kind':'generated','asset_role':'decoration'}]}
    assert required_review(slide)['local_objects']==['img']


def test_aspect_mapping_must_be_explicit_for_letterbox(evidence):
    s=read_json(evidence/'scene.json');slide=s['slides'][0]
    from evidence_contract import review_mapping
    with pytest.raises(ValueError,match='declare review_mapping'):review_mapping(s,slide,[1000,1000])
    slide['review_mapping']={'scale_x':1,'scale_y':1,'offset_x':20,'offset_y':30}
    assert review_mapping(s,slide,[1000,1000])['offset_y']==30


def test_reference_manifest_is_enforced(evidence):
    _,refs,_=reference_snapshot(evidence/'scene.json')
    manifest=evidence/'input/references.json'
    rows=[{'slide':r['index'],'path':r['path'],'size':r['size'],'sha256':r['sha256']} for r in refs]
    write_json(manifest,rows);assert reference_snapshot(evidence/'scene.json')[2]==sha256(manifest)
    rows[0]['sha256']='0'*64;write_json(manifest,rows)
    with pytest.raises(ValueError,match='Reference manifest mismatch'):reference_snapshot(evidence/'scene.json')


def test_positive_evidence_still_passes(evidence):
    assert gate(evidence)['status']=='passed'


def test_scene_cannot_be_omitted_to_bypass_new_gate(evidence):
    r=verify(evidence/'candidate.pptx',evidence/'audit.json',evidence/'fake-office.json',
             evidence/'fake-review.json',evidence/'fake-comparisons/deck-comparison.json')
    assert r['status']=='blocked';assert any('--scene' in x for x in r['pending'])


@pytest.mark.parametrize('name',['visual_local','relationships'])
def test_complex_review_cannot_be_not_applicable(evidence,name):
    p=evidence/'fake-review.json';r=read_json(p);r['checks'][name]={'status':'not_applicable','note':'SYNTHETIC skip attempt'};write_json(p,r)
    result=gate(evidence);assert result['status']=='failed';assert any('cannot be not_applicable: '+name in x for x in result['issues'])


@pytest.mark.parametrize('field',['reference_sha256','render_sha256','slide_id','comparison_json','comparison_json_sha256','scene_sha256','render_receipt_sha256'])
def test_gate_follows_source_and_page_identity_not_just_full_image(evidence,field):
    path,comp=comp_paths(evidence)
    target=comp if field in {'scene_sha256','render_receipt_sha256'} else comp['slides'][0]
    target[field]='missing.json' if field=='comparison_json' else 'WRONG' if field=='slide_id' else '0'*64
    resign_test_comparison(evidence,comp)
    assert gate(evidence)['status']=='failed'


@pytest.mark.parametrize('kind',['side_by_side','overlay','absolute_difference'])
def test_gate_reads_every_local_output(evidence,kind):
    _,comp=comp_paths(evidence);cp=evidence/'fake-comparisons'/comp['slides'][1]['comparison_json']
    detail=read_json(cp);(cp.parent/detail['regions'][1][kind]).unlink()
    result=gate(evidence);assert result['status']=='failed'


def test_local_declaration_cannot_be_deleted_with_resigned_hashes(evidence):
    _,comp=comp_paths(evidence);comp['slides'][1]['local_regions']=[]
    comp['slides'][1]['required_review']={'local_objects':[],'relationship_objects':[]}
    resign_test_comparison(evidence,comp)
    result=gate(evidence);assert result['status']=='failed';assert any('Missing mandatory' in i for i in result['issues'])


def test_missing_per_page_receipt_is_detected(evidence):
    _,comp=comp_paths(evidence);(evidence/'fake-comparisons'/comp['slides'][0]['comparison_json']).unlink()
    assert gate(evidence)['status']=='failed'


def test_reference_changes_invalidate_review_even_when_pptx_unchanged(evidence):
    old=sha256(evidence/'candidate.pptx');Image.new('RGB',(960,540),'black').save(evidence/'ref-1.png')
    assert sha256(evidence/'candidate.pptx')==old
    assert gate(evidence)['status']=='failed'


def test_same_pngs_but_different_receipt_requires_regeneration(evidence):
    p=evidence/'fake-office.json';r=read_json(p);r['test_metadata']='new run';write_json(p,r)
    assert gate(evidence)['status']=='failed'


@pytest.mark.parametrize('mutation',['local_note','local_missing','local_ids','local_evidence','relation_missing','relation_note','full_note_only'])
def test_review_requires_object_level_coverage_and_actual_images(evidence,mutation):
    p=evidence/'fake-review.json';r=read_json(p);local=r['checks']['visual_local'];rel=r['checks']['relationships']
    if mutation=='local_note':local['regions'][0]['note']=' '
    elif mutation=='local_missing':local['regions'].pop()
    elif mutation=='local_ids':local['regions'][0]['object_ids']=[]
    elif mutation=='local_evidence':local['evidence']=[]
    elif mutation=='relation_missing':rel['objects']=[]
    elif mutation=='relation_note':rel['objects'][0]['note']=''
    elif mutation=='full_note_only':r['checks']['visual_full']['evidence']=r['checks']['content_source']['evidence']
    write_json(p,r);assert gate(evidence)['status']!='passed'


def test_simple_page_with_no_local_or_relation_objects_can_finish(tmp_path):
    scene=read_json(ROOT/'examples/three-page-scene.json')
    slide=scene['slides'][0];slide['objects']=slide['objects'][:2];scene['slides']=[slide]
    ref=tmp_path/'ref.png';Image.new('RGB',(960,540),'white').save(ref);slide['reference']=ref.name
    sp=tmp_path/'scene.json';write_json(sp,scene);p=tmp_path/'candidate.pptx';build(sp,p)
    ap=tmp_path/'audit.json';write_json(ap,inspect(p,sp))
    rp=tmp_path/'office.json';write_json(rp,{'status':'passed','renderer':'Microsoft PowerPoint','pptx_sha256':sha256(p),
        'slides':[{'index':1,'file':ref.name,'width':960,'height':540,'sha256':sha256(ref)}]})
    cp=tmp_path/'cmp/deck-comparison.json';c=compare_deck(sp,rp,cp.parent,pptx_path=p)
    note=tmp_path/'note.txt';note.write_text('SYNTHETIC ONLY')
    from verify_delivery import REQUIRED
    checks={n:{'status':'passed','note':'Synthetic only','slides':[1],'evidence':[{'file':note.name,'sha256':sha256(note)}]} for n in REQUIRED}
    full=cp.parent/c['slides'][0]['full_side_by_side'];checks['visual_full']['evidence']=[{'file':full.relative_to(tmp_path).as_posix(),'sha256':sha256(full)}]
    for name in ('visual_local','relationships'):checks[name]={'status':'not_applicable','note':'No such declared objects in this simple test'}
    vp=tmp_path/'review.json';write_json(vp,{'pptx_sha256':sha256(p),'scene_sha256':sha256(sp),'comparison_sha256':sha256(cp),'reviewer':'SYNTHETIC','checks':checks})
    assert verify(p,ap,rp,vp,cp,sp)['status']=='passed'


def test_new_scene_fields_roundtrip_without_changing_content(evidence,tmp_path):
    s=read_json(evidence/'scene.json');s['slides'][0]['review_requirements']={'local_objects':['p01.title']}
    s['slides'][0]['review_mapping']={'scale_x':1,'scale_y':1,'offset_x':0,'offset_y':0}
    sp=evidence/'scene-new.json';write_json(sp,s);p=tmp_path/'new.pptx';build(sp,p)
    assert inspect(p,sp)['checks']['native_content']['status']=='passed'


@pytest.mark.parametrize('entry',['compare_deck.py','verify_delivery.py'])
def test_cli_exposes_new_mandatory_identity_inputs(entry):
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/entry),'--help'],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0
    assert ('--pptx' if entry=='compare_deck.py' else '--scene') in result.stdout


def test_all_local_document_links_resolve():
    assert validate_local_links(ROOT)==[]


def test_pipeline_passes_the_actual_pptx_into_comparison():
    text=(ROOT/'scripts/run_pipeline.py').read_text(encoding='utf-8')
    assert "compare_deck(scene,out/'office/office-render.json',out/'comparisons',regions,pptx_path=pptx)" in text
    assert "review['comparison_sha256']=sha256(out/'comparisons/deck-comparison.json')" in text


def test_zip_uses_standard_utf8_filenames_and_manifest(tmp_path):
    # A complete tiny skill fixture tests the final ZIP itself, no encoding repair.
    root=tmp_path/'src/ppt-reference-rebuild';(root/'scripts').mkdir(parents=True)
    for name,text in [('SKILL.md','---\nname: ppt-reference-rebuild\nmetadata:\n  version: "1.1.1"\n---\n[使用说明](使用说明.md)\n'),
                      ('使用说明.md','[入口](SKILL.md)'),('给模型的启动指令.txt','实际检查'),('scripts/compare_deck.py','# test')]:
        (root/name).write_text(text,encoding='utf-8')
    out=tmp_path/'bundle.zip';result=package(root,out);assert result['status']=='passed'
    with zipfile.ZipFile(out) as z:
        for name in ('使用说明.md','给模型的启动指令.txt'):
            info=z.getinfo('ppt-reference-rebuild/'+name);assert info.flag_bits & 0x800
    assert verify_archive(out)['status']=='passed'
    with pytest.raises(ValueError):package(root,out)


def test_package_rejects_broken_links_and_fonts(tmp_path):
    root=tmp_path/'ppt-reference-rebuild';root.mkdir();(root/'SKILL.md').write_text('metadata:\n  version: "1.1.1"\n[missing](missing.md)')
    with pytest.raises(ValueError,match='Broken local'):package(root,tmp_path/'b.zip')
    (root/'SKILL.md').write_text('metadata:\n  version: "1.1.1"\n');(root/'private-font.ttf').write_bytes(b'no font')
    with pytest.raises(ValueError,match='Forbidden'):package(root,tmp_path/'c.zip')


def test_documented_step_commands_share_one_run_directory_and_execute(evidence,tmp_path):
    """Executes the literal Python examples; substitutes a SYNTHETIC Office step.
    This proves command/path linkage only and must never be reported as Office passed.
    """
    import shlex
    workspace=tmp_path/'documented-run';workspace.mkdir()
    shutil.copytree(ROOT/'scripts',workspace/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'assets',workspace/'assets')
    shutil.copyfile(ROOT/'release.json',workspace/'release.json')
    project=workspace/'new-project';shutil.copytree(evidence,project)
    (project/'evidence').mkdir(exist_ok=True)
    shutil.copyfile(project/'fake-regions.json',project/'evidence/review-regions.json')
    text=(ROOT/'references/tool-runtime.md').read_text(encoding='utf-8')
    block=text.split('<!-- phase1:step-commands:start -->')[1].split('<!-- phase1:step-commands:end -->')[0]
    commands=[shlex.split(line) for line in block.splitlines() if line.startswith(('python ','pwsh '))]
    assert len(commands)==5
    for args in commands:
        if args[0]=='pwsh':
            pp=workspace/args[args.index('-Pptx')+1];out=workspace/args[args.index('-OutputDir')+1]
            sizes=read_json(workspace/args[args.index('-SizesJson')+1]);out.mkdir(parents=True)
            rows=[]
            for size in sizes:
                p=out/f"slide-{size['index']:03}.png";Image.new('RGB',(size['width'],size['height']),'white').save(p)
                rows.append({**size,'file':p.name,'sha256':sha256(p)})
            write_json(out/'office-render.json',{'status':'passed','renderer':'Microsoft PowerPoint',
                       'pptx_sha256':sha256(pp),'slides':rows,'scope':'SYNTHETIC command-path test only'})
        else:
            args[0]=sys.executable
            result=subprocess.run(args,cwd=workspace,capture_output=True,text=True,encoding='utf-8',timeout=20)
            assert result.returncode==0,result.stderr
    run=project/'build/v001'
    assert (run/'comparisons/deck-comparison.json').is_file()
    # No reviewer has signed; the actual gate must still block.
    result=verify(run/'candidate.pptx',run/'audit.json',run/'office/office-render.json',None,
                  run/'comparisons/deck-comparison.json',project/'scene.json')
    assert result['status']=='blocked'


def test_current_entrypoints_reference_one_asset_policy():
    for name in ['SKILL.md','README.md','使用说明.md','给模型的启动指令.txt',
                 'references/assets-and-generation.md','references/shape-construction.md','references/component-recipes.md']:
        text=(ROOT/name).read_text(encoding='utf-8')
        assert 'asset-policy.md' in text,name
        assert '透明PNG/SVG' not in text,name
    assert 'v001-office' not in (ROOT/'references/tool-runtime.md').read_text(encoding='utf-8')


def test_runtime_version_matches_skill_metadata():
    from common import VERSION
    assert VERSION==json.loads((ROOT/'release.json').read_text(encoding='utf-8'))['version']
    assert f'version: "{VERSION}"' in (ROOT/'SKILL.md').read_text(encoding='utf-8')
