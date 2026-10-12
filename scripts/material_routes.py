"""Component material routing; legacy similarity is an Agent assertion."""
from __future__ import annotations

import math
from pathlib import PurePosixPath

THRESHOLD = 75
GUIDANCE = ('先读取当前任务 production_settings，并确定整页背景、分区、前后层次与内容归属。'
            '具体对象的最新明确要求优先，其次按项目已生效设置和已接受路线执行；全局默认只供新项目取用。'
            '图片生成优先时，复杂插画与装饰标题参考局部生成独立高清素材，无需先绘制或填写相似度。'
            '可编辑绘制优先时，按语义拆分原生形状与路径，验证内部编辑；能力不足时说明差距，由用户决定替代。'
            '简单图标使用原生形状与路径，插画依项目制作设置选路。已有素材按来源与质量复用，照片按保真要求处理。'
            '用户要求内部编辑或禁止生图时遵从用户要求；旧计划保留已接受路线，通过范围修订更新。'
            '已选生成路线时，把参考局部交给宿主生图工具，需要透明时生成真实透明 PNG；多个独立素材可同图生成，再分别裁剪放入 PPT。'
            '素材内部原有文字随素材保留，生成时约束可辨识原文；页面独立文字、数字、表格与关系线保持原生。'
            '字体按 font_matching 选择相近字体或精细匹配；文本框按 text_layout 组织段落或逐行定位，不跨栏或卡片合并。'
            '历史方法仅在适用条件满足时采用，不覆盖当前制作设置，也不增加每次必做检查。'
            '旧 low_similarity 记录仍要求绘制稿和低于 75% 的 Agent 判断，分数不代表软件测量或整页验收。')

CONTENT_TYPES = ['background', 'page_text', 'standard_title', 'decorative_title', 'photograph',
                 'simple_icon', 'simple_illustration', 'complex_illustration', 'geometric_graphic', 'existing_asset', 'identity_asset']
REQUIRED_EDITS = ['preserve', 'text', 'geometry', 'data', 'group', 'image_replace', 'unresolved']
TEXT_OWNERSHIPS = ['page', 'asset_title', 'embedded']
EMBEDDED_TEXT_SCHEMA = {'type': 'array', 'items': {
    'type': 'object', 'properties': {
        'text': {'type': 'string', 'maxLength': 5000},
        'legibility': {'enum': ['readable', 'unreadable']},
        'owner_unit_id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$'},
    }, 'required': ['text', 'legibility'], 'additionalProperties': False}, 'maxItems': 100}
DECISION_SCHEMA = {
    'type': 'object', 'properties': {
        'basis': {'enum': ['low_similarity', 'user_request', 'content_category']},
        'reference': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1500},
        'drawing': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'similarity_pct': {'type': 'number', 'minimum': 0, 'maximum': 100},
        'content_type': {'enum': CONTENT_TYPES}, 'required_edit': {'enum': REQUIRED_EDITS},
        'text_ownership': {'enum': TEXT_OWNERSHIPS}, 'embedded_text': EMBEDDED_TEXT_SCHEMA,
        'fidelity': {'enum': ['reference', 'exact']},
    }, 'required': ['basis', 'reference', 'reason'], 'additionalProperties': False,
    'allOf': [
        {'if': {'properties': {'basis': {'const': 'low_similarity'}}},
         'then': {'required': ['drawing', 'similarity_pct'],
                  'properties': {'similarity_pct': {'exclusiveMaximum': THRESHOLD}}}},
        {'if': {'properties': {'basis': {'const': 'content_category'}}},
         'then': {'required': ['content_type', 'required_edit'], 'properties': {
             'content_type': {'enum': ['simple_illustration', 'complex_illustration', 'decorative_title', 'photograph', 'existing_asset']},
             'required_edit': {'enum': ['image_replace', 'group']}}}},
        {'if': {'properties': {'content_type': {'const': 'decorative_title'}},
                'required': ['content_type']},
         'then': {'required': ['text_ownership', 'embedded_text'], 'properties': {
             'text_ownership': {'const': 'asset_title'},
             'embedded_text': {'contains': {'properties': {
                 'legibility': {'const': 'readable'}, 'text': {'type': 'string', 'pattern': '\\S'}},
                 'required': ['text', 'legibility']}, 'minContains': 1}}}},
    ],
}


def validate_decision(value, project=None):
    import jsonschema
    errors = list(jsonschema.Draft202012Validator(DECISION_SCHEMA).iter_errors(value))
    if errors:
        raise ValueError('generation_decision: ' + errors[0].message)
    if not isinstance(value['reason'], str) or not value['reason'].strip() or len(value['reason'])>1500:
        raise ValueError('Record the Agent comparison reason or the explicit user request')
    if value['basis']=='low_similarity' and not {'drawing','similarity_pct'}<=value.keys():
        raise ValueError('Low-similarity generation requires a drawing and Agent similarity_pct')
    score=value.get('similarity_pct')
    if 'similarity_pct' in value:
        try: finite = math.isfinite(score)
        except (TypeError, OverflowError): finite = False
        if type(score) not in (int,float) or not 0<=score<=100 or not finite:
            raise ValueError('Agent similarity_pct must be a finite number from 0 to 100')
        if value['basis']=='low_similarity' and score>=THRESHOLD:
            raise ValueError('Default generation fallback requires Agent similarity below 75%; follow an explicit user request separately')
    if value.get('content_type') in {'identity_asset', 'page_text', 'standard_title'}:
        raise ValueError('Preserve source materials and keep standalone page text native')
    if value.get('fidelity') == 'exact':
        raise ValueError('Exact source fidelity cannot be regenerated')
    if value.get('content_type') == 'simple_icon' and value['basis'] != 'user_request':
        raise ValueError('Simple icons require native editing unless explicitly requested by the user')
    if value.get('required_edit') in {'preserve', 'text', 'geometry', 'data', 'unresolved'}:
        raise ValueError('Generation conflicts with the component edit requirement')
    if value.get('text_ownership') == 'page':
        raise ValueError('Standalone page text cannot be generated inside artwork')
    if value.get('embedded_text') and value.get('text_ownership') not in {'asset_title', 'embedded'}:
        raise ValueError('Embedded text needs asset_title or embedded ownership')
    for item in value.get('embedded_text', []):
        if item['legibility'] == 'readable' and not item['text'].strip():
            raise ValueError('Readable embedded text needs its exact source text')
        if item['legibility'] == 'unreadable' and item['text']:
            raise ValueError('Do not guess unreadable embedded text')
    for field in ('reference','drawing'):
        if field not in value:continue
        name=value[field]
        if (not isinstance(name,str) or not name.strip() or len(name)>500 or '\\' in name or ':' in name
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts):
            raise ValueError(field+' must be a project-relative file path')
        if project is not None:
            if __package__:
                from .common import resolve_asset
            else:
                from common import resolve_asset
            resolve_asset(project,name)
    return value


def generated_illustration(obj, project=None):
    """Generated component artwork retains standalone text and source rules."""
    if obj.get('source_kind') == 'generated' and obj.get('raster_content') == 'photograph':
        if obj.get('asset_role') != 'photo':
            raise ValueError('Generated photograph must retain photo role and generated provenance')
        validate_decision(obj.get('generation_decision'), project)
        if obj['generation_decision'].get('content_type') != 'photograph':
            raise ValueError('Generated photograph requires photograph content declaration')
        return True
    if obj.get('raster_content')!='generated_illustration':return False
    if obj.get('source_kind')!='generated' or obj.get('asset_role') not in {'icon','decoration'}:
        raise ValueError('Generated illustration fallback is limited to generated icons or illustrations; logos and source photographs keep their original rules')
    validate_decision(obj.get('generation_decision'),project)
    return True
