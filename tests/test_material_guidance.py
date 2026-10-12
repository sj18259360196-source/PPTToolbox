"""Exercise generated startup, preparation, regional packets and host handoffs."""
import base64
import io
import json

from PIL import Image

from test_tools import ROOT
from test_workflow import ref, respond
from common import read_json
from toolbox_manager.service import Manager
from toolbox_manager.production_storage import startup_prompt
from toolbox_manager import preparation
from asset_ops import prepare_generation
import workflow as wf


def test_actual_startup_and_preparation_default_prompts_preserve_materials(tmp_path):
    manager = Manager(tmp_path/'manager',root=ROOT,home=tmp_path/'home')
    startup = startup_prompt(manager)['text']
    assert '新项目保存创建时的全局默认' in startup
    assert '新项目默认 generate_first' not in startup
    for phrase in ('复杂插画与装饰标题','照片按用户保真要求决定保留或生成','内部编辑按项目绘制偏好与具体对象要求执行',
                   'request_asset 的 request.items','先恢复已完成','左右对比和叠加图','native_first'):
        assert phrase in startup
    work = tmp_path/'projects'
    work.mkdir()
    row = preparation.create(manager,{'id':'1271'+'0'*28,'name':'Guidance fixture','root':str(work)})
    stream = io.BytesIO()
    Image.new('RGB',(40,20),'white').save(stream,format='PNG')
    row = preparation.upload(manager,{'id':row['id'],'revision':row['revision'],'name':'reference.png',
                                      'data':base64.b64encode(stream.getvalue()).decode()})
    prompt = preparation.prompt(manager,row['id'])['text']
    assert '页面独立文字可编辑' in prompt
    assert '复杂插画与装饰标题可用独立素材' in prompt
    assert '照片和素材自带文字保留' in prompt
    assert '整体移动、缩放和替换' in prompt
    assert not (work/'project').exists()


def test_issued_regional_packet_and_examples_explain_compatible_native_flag(tmp_path):
    project = tmp_path/'project'
    wf.start(project,[ref(tmp_path)])
    respond(project,{'regions':[{'id':'art','bbox':[0,0,640,360],'role':'diagram',
                                'summary':'Decorative title and independent material'}]})
    task = wf.next_task(project)['task']
    packet = read_json(task['packet'])
    context = packet['context']
    assert context['native_first'] is True
    assert '不要求全页原生' in context['native_first_meaning']
    assert 'not a requirement to redraw every material' in context['submission_constraints']['native_first_meaning']
    instructions = packet['instructions']
    assert '保留照片与插图内部文字' in instructions
    assert '无需先做原生试画' in instructions
    advice = context['production_guidance']
    assert '图片生成优先时，复杂插画与难以匹配的装饰标题可直接参考生成' in advice['asset_selection']
    assert '可编辑绘制优先时' in advice['asset_selection']
    assert 'simple_icon 简单图标两种模式都原生绘制' in advice['asset_selection']
    assert '照片按用户保真要求决定保留或参考生成' in advice['asset_selection']
    assert '已有素材按来源资格与编辑要求选路' in advice['asset_selection']
    assert '素材自带文字随素材保留' in advice['asset_selection']
    assert '准确标识优先保留原件或源像素' in advice['native_first']
    examples = read_json(task['examples_file'])
    assert '照片与插画内部文字随素材保留' in examples['instructions']
    options = context['submission_constraints']['asset_requests']
    assert 'request_assets creates separate jobs' in options['completion']
    assert 'Start with 2..8' in options['sheet_completion']


def test_real_title_and_batch_handoffs_keep_text_scoped_per_item(tmp_path):
    project = tmp_path/'project'
    wf.start(project,[ref(tmp_path)])
    respond(project,{'regions':[{'id':'art','bbox':[0,0,640,360],'role':'diagram',
                                'summary':'Title and separate icon'}]})
    title = {'basis':'content_category','reference':'input/slide-001.png',
             'reason':'Decorative title needs whole-component replacement',
             'content_type':'decorative_title','required_edit':'image_replace',
             'text_ownership':'asset_title','embedded_text':[{'text':'准确标题','legibility':'readable'}]}
    icon = {'basis':'content_category','reference':'input/slide-001.png',
            'reason':'Complex icon whole-component replacement',
            'content_type':'complex_illustration','required_edit':'image_replace'}
    respond(project,{'action':'request_asset','request':{
        'id':'sheet','purpose':'Title and independent icon','prompt':'Synthetic handoff only',
        'transparent':True,'allowed_approximation':True,'multi_icon_sheet':True,
        'items':[{'id':'title','purpose':'Title','generation_decision':title},
                 {'id':'icon','purpose':'Icon','generation_decision':icon}]}})
    handoff = prepare_generation(project,project/'handoff')
    assert handoff['output_contract']['text_contract_scope'] == 'items[].text_contract'
    assert handoff['items'][0]['text_contract']['allowed_material_text'][0]['text'] == '准确标题'
    assert handoff['items'][1]['text_contract']['allowed_material_text'] == []
    assert 'do not combine them into a scene' in handoff['instructions']
    assert 'rerun only the pending retry items' in handoff['instructions']
    packet = read_json(wf.next_task(project)['task']['packet'])
    assert '装饰标题保存原文并逐字核对' in packet['instructions']
    assert '插画内部文字保留在图内' in packet['instructions']
    assert handoff['visual_review_status'] == 'not_run'


def test_initialized_analysis_task_uses_component_editing_defaults(tmp_path):
    from init_project import initialize
    project = tmp_path/'analysis'
    initialize(project,[ref(tmp_path)])
    text = (project/'TASK.md').read_text(encoding='utf-8')
    assert '背景、分区、层级' in text
    assert '当前 production_settings' in text
    assert '照片按用户保真要求决定保留或参考生成' in text
    assert '准确身份和明确原件保留约束继续有效' in text
    assert '已有素材按来源资格与编辑要求选路' in text
    assert '图片生成优先时，复杂插画与装饰标题可直接参考生成独立素材' in text
    assert '可编辑绘制优先时，使用真实原生形状或路径' in text
    assert 'simple_icon 简单图标在两种模式下都原生绘制' in text
    assert '简单插画按模式与轮廓选路' in text
