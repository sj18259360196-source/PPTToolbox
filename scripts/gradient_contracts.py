"""Discoverable bounded contracts shared by manager and tests."""
from graphics_recipe import obj,array,STYLE,ID
S={'type':'string','minLength':1}
HASH={'type':'string','pattern':'^[a-f0-9]{64}$'}
TIME={'type':'integer','minimum':5,'maximum':180}
UNIT={'type':'number','minimum':0,'maximum':1}
COLOR={'type':'string','pattern':'^[0-9A-Fa-f]{6}$'}
SOURCE={'project':S,'pptx':S,'pptx_sha256':HASH,'timeout_seconds':TIME}
OP_BASE={'slide':{'type':'integer','minimum':1},'name':S,'expected':{'type':['string','number']},'value':{'type':['string','number']}}
OPERATIONS=array({'oneOf':[
 obj({**OP_BASE,'op':{'const':'gradient.angle'}},(*OP_BASE,'op')),
 obj({**OP_BASE,'op':{'const':'gradient.stop'},'index':{'type':'integer','minimum':1,'maximum':16},
      'property':{'enum':['color','alpha','position']}},(*OP_BASE,'op','index','property'))]},64,1)
LAYERED=obj({'frame':array({'type':'integer','minimum':8,'maximum':4000000},2,2),
 'background':COLOR,'provenance':S,'timeout_seconds':{'type':'integer','minimum':1,'maximum':60},
 'components':array(obj({'id':ID,'angle_deg':{'type':'number','minimum':0,'exclusiveMaximum':360},
                       'fill_alpha':UNIT,'stop_alpha':UNIT},('id','angle_deg','fill_alpha','stop_alpha')),6,1),
 'layer_counts':{'type':'array','minItems':1,'maxItems':4,'uniqueItems':True,
                 'items':{'type':'integer','minimum':1,'maximum':6}}},
 ('frame','background','provenance','components','layer_counts'))
SCENE=obj({'scene':S,'sha256':HASH},('scene','sha256'))
SPECS={
 'probe_gradient':('生成有界原生渐变小样并读取实际 Office 渲染与属性，不自动批准视觉。',
    obj({'project':S,'timeout_seconds':TIME,'background':COLOR,'samples':array(obj({'style':STYLE,
         'size':array({'type':'number','minimum':10,'maximum':130},2,2)},('style',)),9,1)},('project','samples'))),
 'gradient_roundtrip':('在独立副本修改渐变色标与角度，保存重开读回并导出图像。',
    obj({**SOURCE,'operations':OPERATIONS},('project','pptx','pptx_sha256','operations'))),
 'scene_preflight':('按场景文件目录预检路径、结构及证据字段，不导入或修改项目。',
    obj({'project':S,'scene':S},('project','scene'))),
 'select_versions':('核对哈希、坐标框与背景依赖，返回历史原生组拼选提案，不自动采用。',
    obj({'project':S,'base':SCENE,'selections':array(obj({'scene':S,'sha256':HASH,'slide':S,'id':S,
         'dependencies':array(S,32,1)},('scene','sha256','slide','id','dependencies')),32,1)},('project','base','selections')))
}
