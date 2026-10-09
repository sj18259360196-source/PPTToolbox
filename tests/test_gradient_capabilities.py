import copy
import sys
from pathlib import Path
import pytest
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from graphics_recipe import compile_recipe
from office_edit import validate_operations,read_value,apply_edit

def material():
 return {'format':'graphics-recipe/1','id':'material','canvas':[200,200],
  'paths':[{'id':'outline','closed':True,'visible':False,'commands':[['M',10,10],['L',180,10],['L',180,180],['L',10,180],['Z']]}],
  'material_groups':[{'id':'surface','source':'outline','layers':[
    {'id':'base','style':{'line':None,'gradient':{'type':'linear','angle_deg':20,'stops':[
        {'position':0,'color':'2233AA'},{'position':.5,'color':'8822BB'},{'position':1,'color':'CC4455'}]}}},
    {'id':'light','style':{'line':None,'fill_alpha':.6,'gradient':{'type':'linear','angle_deg':110,'stops':[
        {'position':0,'color':'FFFFFF','alpha':0},{'position':1,'color':'FFEEAA','alpha':.7}]}}}]}],
  'order':['surface']}

def test_shared_outline_regeneration_and_conflict():
 r=material();a=compile_recipe(r);r['paths'][0]['commands'][1][1]=160
 b=compile_recipe(r,a,a['objects'])
 assert b['objects'][0]['children'][0]['commands']==b['objects'][0]['children'][1]['commands']
 assert b['changed']==['surface'] and b['dependencies']['surface']==['outline']
 changed=copy.deepcopy(a['objects']);changed[0]['children'][0]['commands'][1][1]=170
 with pytest.raises(ValueError,match='conflict'):compile_recipe(r,a,changed)

def test_layer_id_and_open_path_rejected():
 r=material();r['material_groups'][0]['layers'][1]['id']='base'
 with pytest.raises(ValueError,match='Duplicate'):compile_recipe(r)
 r=material();r['paths'][0]['closed']=False;r['paths'][0]['commands'].pop()
 with pytest.raises(ValueError,match='closed'):compile_recipe(r)

@pytest.mark.parametrize('prop,val',[('alpha',2),('position',float('nan')),('color','XYZ')])
def test_gradient_invalid_values(prop,val):
 with pytest.raises(ValueError):validate_operations([{'op':'gradient.stop','slide':1,'name':'a','index':1,'property':prop,'expected':0,'value':val}])

def test_layered_holdout_and_effective_alpha():
 from gradient_layered import fit
 opt={'frame':[32,32],'background':'FFFFFF','provenance':'synthetic-test','layer_counts':[1,2],
      'components':[{'id':'a','angle_deg':0,'fill_alpha':.8,'stop_alpha':.5},
                    {'id':'b','angle_deg':90,'fill_alpha':.5,'stop_alpha':.5}], 'timeout_seconds':5}
 image=Image.fromarray(np.full((32,32,3),180,dtype=np.uint8))
 result=fit(image,Image.new('L',(32,32),255),opt)
 assert result['validation_samples']>0 and result['selected']
 assert result['candidates'][0]['effective_alpha'][0]==.4
 assert result['adopted'] is False
 with pytest.raises(ValueError,match='mask'):fit(image,None,opt)

def test_registered_schemas():
 from toolbox_manager.graphics import SPECS
 from jsonschema import Draft202012Validator
 for _,schema in SPECS.values():Draft202012Validator.check_schema(schema)
 assert {'probe_gradient','gradient_roundtrip','scene_preflight','select_versions'}<=SPECS.keys()

def test_release_uses_verified_runtime_not_development_wheels(tmp_path):
 from distribution.build_portable import source_files
 p=tmp_path/'toolbox_manager/vendor/graphics/scipy';p.mkdir(parents=True)
 (p/'development.cp311.pyd').write_bytes(b'development')
 (tmp_path/'toolbox_manager/graphics.py').write_text('# source',encoding='utf-8')
 assert 'toolbox_manager/graphics.py' in source_files(tmp_path,release=True)
 assert not any('/vendor/' in p for p in source_files(tmp_path,release=True))
 assert any('/vendor/' in p for p in source_files(tmp_path,release=False))

def test_preflight_and_selection_protection(tmp_path):
 from gradient_capabilities import preflight,select_versions
 from common import write_json,sha256
 scene=compile_recipe(material())['scene'];bg=copy.deepcopy(scene['slides'][0]['objects'][0]);bg['id']='bg'
 for c in bg['children']:c['id']='bg_'+c['id']
 scene['slides'][0]['objects'].insert(0,bg)
 p=tmp_path/'a.json';write_json(p,scene)
 assert preflight(tmp_path,{'scene':'a.json'})['status']=='valid'
 choice={'scene':'a.json','sha256':sha256(p),'slide':'graphics','id':'surface','dependencies':['bg']}
 args={'base':{'scene':'a.json','sha256':sha256(p)},'selections':[choice]}
 assert select_versions(tmp_path,args)['mutated'] is False
 choice['sha256']='0'*64
 with pytest.raises(ValueError,match='Stale'):select_versions(tmp_path,args)

def test_bounded_worker_timeout_preserves_source(tmp_path,monkeypatch):
 from build_pptx import build
 from common import write_json,sha256
 from gradient_jobs import run_job
 import subprocess
 scene=tmp_path/'scene.json';write_json(scene,compile_recipe(material())['scene'])
 ppt=tmp_path/'a.pptx';build(scene,ppt);before=sha256(ppt)
 def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('fixture',5)
 monkeypatch.setattr(subprocess,'run',timeout)
 result=run_job(tmp_path,'read_properties',{'pptx':'a.pptx','pptx_sha256':before,
     'targets':[{'slide':1,'id':'surface_base'}],'timeout_seconds':5})
 assert result['status']=='outcome_unknown' and result['source_unchanged']
 assert (Path(result['directory'])/'stage.json').is_file() and sha256(ppt)==before

def test_selected_native_geometry_only(tmp_path):
 from native_nodes import summary
 from build_pptx import build
 from common import write_json
 scene=tmp_path/'scene.json';write_json(scene,compile_recipe(material())['scene'])
 ppt=tmp_path/'a.pptx';build(scene,ppt)
 assert set(summary(ppt,targets={(1,'surface_base')}))=={'1/surface_base'}

def test_gradient_com_adapter_position_and_alpha():
 from types import SimpleNamespace
 from office_edit import read_value,apply_edit
 class Stops:
  Count=3
  def __init__(self):self.rows=[SimpleNamespace(Position=x,Transparency=.2,Color=SimpleNamespace(RGB=0)) for x in [0,.5,1]]
  def Item(self,n):return self.rows[n-1]
 shape=SimpleNamespace(Fill=SimpleNamespace(Type=3,GradientStops=Stops()))
 op={'op':'gradient.stop','slide':1,'name':'a','index':2,'property':'position','expected':.5,'value':1}
 with pytest.raises(ValueError,match='reorder'):apply_edit(shape,op)
 op.update(property='alpha',value=.35);apply_edit(shape,op)
 assert abs(read_value(shape,op)-.35)<1e-8

def test_new_operations_are_governed(tmp_path):
 from toolbox_manager.service import Manager
 from toolbox_manager.policy import PolicyDenied
 from toolbox_manager.mcp import MCP
 manager=Manager(tmp_path/'data',root=ROOT,home=tmp_path/'home')
 project=tmp_path/'project';project.mkdir();manager.authorize_project(project,[])
 with pytest.raises(PolicyDenied,match='disabled'):
  manager.graphics('probe_gradient',{'project':str(project),'samples':[{'style':{'fill':'FF0000'}}]})
 package=manager.package()
 with manager.store.db() as db:db.execute('INSERT INTO overrides VALUES(?,?,?,?)',(package['id'],'tool','graphics.scene_preflight','false'))
 with pytest.raises(PolicyDenied,match='disabled'):
  manager.graphics('scene_preflight',{'project':str(project),'scene':'missing.json'},source='owner')
