"""Managed illustration route, path fitting and comparison contracts."""
from graphics_recipe import obj, array
S={'type':'string','minLength':1,'maxLength':2000}
SHA={'type':'string','pattern':'^[a-f0-9]{64}$'}
OBS=obj({
 'limited_palette':{'type':['boolean','null']},
 'semantic_layers':{'type':['boolean','null']},
 'boundary':{'enum':['curved','mixed','faceted','texture','unknown']},
 'layer_editing_required':{'type':'boolean'},
 'evidence_note':S},('limited_palette','semantic_layers','boundary','layer_editing_required','evidence_note'))
BASE={'project':S}
SPECS={
 'route_illustration':('按 Agent 已查看的图形特征返回适用、排除或局部试验路线；不自动识图。',
    obj({**BASE,'observations':OBS},('observations',))),
 'fit_paths':('在已授权项目中按锚点和采样偏差约束拟合原生闭合路径，保留候选及报告，不自动采用。',
    obj({**BASE,'input_file':S,'input_sha256':SHA,'observations':OBS,
         'rms':{'type':'number','exclusiveMinimum':0,'maximum':5},
         'max_error':{'type':'number','exclusiveMinimum':0,'maximum':10},
         'anchors':{'type':'object','maxProperties':128,'additionalProperties':array(array({'type':'number','minimum':-100000,'maximum':100000},2,2),64)}},
        ('project','input_file','input_sha256','observations'))),
 'compare_regions':('按显式掩膜测量 IoU、双向边界距离及共同内部区域颜色误差，不配准、不评审通过。',
    obj({**BASE,'reference':S,'candidate':S,'reference_mask':S,'candidate_mask':S,
         'sha256':obj({k:SHA for k in ['reference','candidate','reference_mask','candidate_mask']},
                      ('reference','candidate','reference_mask','candidate_mask')),
         'pixels_per_reference_pixel':{'type':'number','exclusiveMinimum':0,'maximum':64},
         'erosion_pixels':{'type':'integer','minimum':0,'maximum':32}},
        ('project','reference','candidate','reference_mask','candidate_mask','sha256','pixels_per_reference_pixel')))
}

# Optional observed risks preserve the original route API.
for key in ('gradients_or_fringes','thin_branches','many_holes','mixed_boundary_colors',
            'separable_regions','shared_edges_known','ranking_reversal','topology_changed'):
    OBS['properties'][key]={'type':['boolean','null']}
from illustration_method_contracts import SPECS as METHOD_SPECS
SPECS.update(METHOD_SPECS)
