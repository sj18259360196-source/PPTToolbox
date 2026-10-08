"""Per-illustration Agent decisions, not an automatic similarity metric."""
from __future__ import annotations

import math
from pathlib import PurePosixPath

THRESHOLD = 75
GUIDANCE = ('插图和图标默认先由 Agent 绘制，再对照参考局部判断相似度。'
            'Agent 判断低于 75% 时可以转入 AI 生图，并记录参考图、绘制稿、分数和理由。'
            '用户明确要求直接生图时可跳过绘制；要求原生可编辑或禁止生图时遵从用户要求。'
            '把参考局部交给宿主生图工具，优先生成透明背景 PNG；多个图标可同图生成，再分别裁剪放入 PPT。'
            '分数是 Agent 的局部判断，不是软件测量或整页验收分数。文字、数字、表格与关系线继续保持可编辑。')


def validate_decision(value, project=None):
    required = {'basis', 'reference', 'reason'}
    optional = {'drawing', 'similarity_pct'}
    if not isinstance(value, dict) or required-value.keys() or value.keys()-required-optional:
        raise ValueError('generation_decision requires basis, reference, reason; drawing and similarity_pct are optional only for user_request')
    if not isinstance(value['basis'],str) or value['basis'] not in {'low_similarity', 'user_request'}:
        raise ValueError('Generation basis must be low_similarity or user_request')
    if not isinstance(value['reason'], str) or not value['reason'].strip() or len(value['reason'])>1500:
        raise ValueError('Record the Agent comparison reason or the explicit user request')
    if value['basis']=='low_similarity' and not {'drawing','similarity_pct'}<=value.keys():
        raise ValueError('Low-similarity generation requires a drawing and Agent similarity_pct')
    score=value.get('similarity_pct')
    if 'similarity_pct' in value:
        if type(score) not in (int,float) or not 0<=score<=100 or not math.isfinite(score):
            raise ValueError('Agent similarity_pct must be a finite number from 0 to 100')
        if value['basis']=='low_similarity' and score>=THRESHOLD:
            raise ValueError('Default generation fallback requires Agent similarity below 75%; follow an explicit user request separately')
    for field in ('reference','drawing'):
        if field not in value:continue
        name=value[field]
        if (not isinstance(name,str) or not name.strip() or len(name)>500 or '\\' in name or ':' in name
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts):
            raise ValueError(field+' must be a project-relative file path')
        if project is not None:
            from common import resolve_asset
            resolve_asset(project,name)
    return value


def generated_illustration(obj, project=None):
    """A narrow exception to native-first artwork, retaining ordinary text/data rules."""
    if obj.get('raster_content')!='generated_illustration':return False
    if obj.get('source_kind')!='generated' or obj.get('asset_role') not in {'icon','decoration'}:
        raise ValueError('Generated illustration fallback is limited to generated icons or illustrations; logos and source photographs keep their original rules')
    validate_decision(obj.get('generation_decision'),project)
    return True
