"""Contract checks use fixture pixels, not OCR or actual visual acceptance."""
import copy
import pytest
from PIL import Image
from common import sha256
from material_text_review import requirements, validate


def fixture(tmp_path):
    asset=tmp_path/'title.png'
    Image.new('RGBA',(64,32),(20,40,60,180)).save(asset)
    objects=[{'id':'title','kind':'image','asset':'title.png','source_kind':'generated',
              'generation_decision':{'text_ownership':'asset_title','embedded_text':[
                  {'text':'准确标题 2026','legibility':'readable'}]}}]
    result={'status':'passed','viewed_files':[str(asset)],'material_text_checks':[
        {'object_id':'title','asset_sha256':sha256(asset),'observed_text':['准确标题 2026']}]}
    return asset, objects, result


def test_generated_title_exact_observation_and_hash(tmp_path):
    asset,objects,result=fixture(tmp_path)
    assert requirements(objects,tmp_path)[0]['expected_text']==['准确标题 2026']
    validate(result,objects,tmp_path)
    result['viewed_files']=['title.png']
    validate(result,objects,tmp_path)
    result['material_text_checks'][0]['observed_text']=['准确标题2026']
    with pytest.raises(ValueError,match='differs'):validate(result,objects,tmp_path)
    result['status']='needs_changes'
    validate(result,objects,tmp_path)
    result['material_text_checks'][0]['asset_sha256']='0'*64
    with pytest.raises(ValueError,match='different image bytes'):validate(result,objects,tmp_path)


def test_generated_title_requires_view_and_complete_checks(tmp_path):
    _,objects,result=fixture(tmp_path)
    missing=copy.deepcopy(result);missing.pop('material_text_checks')
    with pytest.raises(ValueError,match='exact material_text_checks'):validate(missing,objects,tmp_path)
    result['viewed_files']=[]
    with pytest.raises(ValueError,match='actual generated image'):validate(result,objects,tmp_path)


def test_intrinsic_photo_text_needs_no_editable_transcription(tmp_path):
    _,objects,result=fixture(tmp_path)
    objects[0]['source_kind']='user_asset'
    assert requirements(objects,tmp_path)==[]
    validate({'status':'passed','viewed_files':[]},objects,tmp_path)


def test_unreadable_generated_internal_text_is_not_invented(tmp_path):
    _,objects,result=fixture(tmp_path)
    objects[0]['generation_decision']['embedded_text']=[{'text':'','legibility':'unreadable'}]
    assert requirements(objects,tmp_path)==[]
    validate({'status':'passed','viewed_files':[]},objects,tmp_path)
