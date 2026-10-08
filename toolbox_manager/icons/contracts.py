"""One strict API contract for the icon UI, CLI and MCP."""
S={'type':'string'}
N={'type':'number'}
META={'type':'object','properties':{**{k:S for k in ('name','collection','style','author','license','source_url','source_revision','origin','notes')},
    'tags':{'type':'array','items':S},'aliases':{'type':'array','items':S}},'required':['name','author','license','origin'],'additionalProperties':False}
def obj(properties=None,required=()):return {'type':'object','properties':properties or {},'required':list(required),'additionalProperties':False}
V={'version':S}
IMPORT=obj({'svg':S,'metadata':META,'parent':S,'reference':S},('svg','metadata'))
SPECS={
 'search':('检索中英文标签或参考图外观；科研语义需要 Agent 核对。Agent 默认省略预览图片，可用 icons_inspect 按需读取。',obj({'query':S,'collection':S,'style':S,'include_drafts':{'type':'boolean'},'include_previews':{'type':'boolean'},'limit':{'type':'integer','minimum':1,'maximum':100},'reference':S})),
 'inspect':('读取固定版本的 SVG、原生配方和验证记录。',obj(V,('version',))),
 'stats':('查看本地图标库和专题包。',obj()),
 'providers':('读取重绘适配器可用状态。',obj()),
 'import':('将 SVG 与来源保存为不可变草稿版本。',IMPORT),
 'batch':('批量导入 SVG，每项独立报告成功或失败。',obj({'items':{'type':'array','items':IMPORT,'minItems':1,'maxItems':100}},('items',))),
 'validate':('计算 SVG 转换差异和结构证据；不自动认定视觉通过。',obj({**V,'reference':S},('version',))),
 'fragment':('获取可提交到 region_objects 的原生对象分组，不改写项目。',obj({**V,'box':{'type':'array','items':N,'minItems':4,'maxItems':4},'prefix':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,60}$'},'color':S,'stroke_width':N,'points_per_unit':{'type':'number','exclusiveMinimum':0}},('version',))),
 'trace_fragment':('将已分离的单个语义部件黑白蒙版转为原生轮廓草稿，保留小岛和孔洞。不接收彩色图片，不写入全局库，不自动批准视觉质量。',obj({'mask':S,'smoothing':{'type':'string','enum':['none','curves']},'simplify_error_px':{'type':'number','anyOf':[{'const':0},{'minimum':.05,'maximum':.5}]},'semantic_name':{'type':'string','minLength':3,'maxLength':120},'box':{'type':'array','items':N,'minItems':4,'maxItems':4},'prefix':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,60}$'},'color':{'type':'string','pattern':'^[0-9a-fA-F]{6}$'}},('mask','semantic_name','box','prefix'))),
 'place':('将固定版本的原生 PPTX 和 scene 复制到已授权项目素材目录，不覆盖当前候选。',obj({**V,'project':S,'project_key':S,'color':S,'stroke_width':N},('version',))),
 'redraw_start':('建立最多三次提交的 Agent 重绘任务，返回部件绘制要求。',obj({'brief':S,'reference':S},('brief',))),
 'redraw_submit':('提交 Agent 绘制的 SVG，保存草稿并返回对比证据。',obj({'job':S,'svg':S,'metadata':META},('job','svg','metadata'))),
 'trace':('用 VTracer 获得轮廓草稿，需 Agent 继续简化和语义核对。',obj({'reference':S,'metadata':META},('reference','metadata'))),
 'model_generate':('调用用户配置的本机 SVG 模型服务，结果仍需核对。',obj({'brief':S,'reference':S,'metadata':META},('brief','metadata'))),
}
OWNER_SPECS={'review':obj({**V,'decision':{'enum':['approve','reject']},'note':S},('version','decision','note'))}

def validate(op,args,owner=False):
    from jsonschema import Draft202012Validator
    schema=OWNER_SPECS.get(op) if owner and op in OWNER_SPECS else SPECS[op][1]
    errors=list(Draft202012Validator(schema).iter_errors(args))
    if errors:raise ValueError(errors[0].message)
