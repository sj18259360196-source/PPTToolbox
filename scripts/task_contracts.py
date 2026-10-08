"""Small, explicit input contracts exposed before an Agent authors a response.
Does not insert guessed semantic roles or accept a placeholder as an actual asset.
"""
from __future__ import annotations
from pathlib import Path
from common import read_json, TASK_REVIEW_STATUSES
from evidence_contract import RESERVED_IDS
from workflow_scene import ROLES, keys, text

ROUTES = {'native', 'crop', 'user_asset', 'external', 'generated'}


def constraints(kind, context):
    if kind in {'source_review','review_full','review_local','preview_full','preview_local',
                'editable_behavior','reproducibility'}:
        result = {
            'status_enum': list(TASK_REVIEW_STATUSES),
            'report_status_is_not_task_status': 'failed/not_run/not_applicable are report-only; use needs_changes for a failed task check.',
            'viewed_files': 'Only list files actually opened. Required files are in the task packet; a file listing is not an observation.',
            'observations': 'Name the affected text/object/region and actual difference. Unresolved visible defects require needs_changes.',
            'identity': 'Keep task_id, token and base_revision from this task. Do not replay an accepted submission.',
        }
        if kind in {'review_full','preview_full'}:
            result['required_checks'] = ['visual_full','raster_scope','text_geometry']
        if kind in {'review_local','preview_local'}:
            result['relationship_ids'] = context.get('relationships', [])
        if kind == 'source_review':
            result['element_scope'] = {
                'required_when_present': 'scope_review with current revision and every source unit exactly once; each row has unit_id, status, note.',
                'review': 'Inspect original source and task requirement independently. Check ownership, omitted text, preserved artifacts and conflicting evidence. A declared label or digest is not semantic proof.',
                'completion': 'Unresolved units forbid passed. Every native text object needs exact text_checks. Tables and chart labels require source review even without separate text objects.',
            }
            result['first_checks'] = ['proper names and symbols','numbers and units','omitted source content']
            result['text_checks'] = {
                'optional': True,
                'rows': {'object_id': 'Current text object ID', 'source_text': 'Exact text read from the original reference'},
                'rule': 'When supplied, use a nonempty list with unique text object IDs. Exact differences forbid passed; use needs_changes or blocked. Preserve punctuation and whitespace.',
                'scope': 'These are explicit spot checks, not proof of complete source coverage. Inspect the original independently; do not copy candidate text as evidence. Tables remain part of the source review.',
            }
        if kind == 'editable_behavior':
            result['required_action_kinds'] = context.get('required_edit_actions', [])
            result['additional_checks'] = [
                'Move intended groups together and reopen the copy.',
                'Replace a representative label with a longer sentence and inspect wrapping.',
                'Change actual chart data where present; native bars are not linked data charts.',
            ]
        return result
    if kind == 'page_plan':
        from element_scope import SCOPE
        return {'element_scope_schema': SCOPE,
                'element_scope_guidance': [
                    'For newly authored plans include element_scope version 1 and revision 1. Legacy plans remain readable. On replan retain stable source IDs and increment revision.',
                    'Read the user task before assigning required_edit. Record task_requirement and each unit requirement, semantic_role, input_form, owner_id, evidence and counterevidence. Do not infer scope from OCR or object kind alone.',
                    'Cover every region and all source content, including uncertain candidates. Use unresolved for a genuine conflict; never drop an obligation to obtain a pass.',
                    'A cited poster may require preserve; an explicit request to edit that same poster requires text. Full-slide text screenshots do not qualify for automatic preservation.',
                    'Separate semantic ownership from geometry, draw_order and production order. Analyze whole page then modules; keep existing back-to-front assembly.',
                    'Preserved raster needs source asset, sha256 and optional exact source crop. Preserve native source using native_sha256 of logical objects via element_scope.native_digest; never rasterize native content for protection.',
                    'Keep ambiguous candidates visible; ask only when the actual requirement conflict remains unresolved.',
                ],
                'region_id': {'pattern': '[A-Za-z0-9][A-Za-z0-9_-]{0,39}',
                              'reserved_case_insensitive': sorted(RESERVED_IDS),
                              'unique_case_insensitive': True},
                'role_enum': sorted(ROLES),
                'bbox': {'format': 'xyxy', 'units': 'source_pixels',
                         'limits': context['reference_size'], 'integer': True},
                'required_per_region': ['id', 'bbox', 'role', 'summary'],
                'note': '角色从枚举选择，summary自由描述；例如对比栏可用diagram，ID可写scene_pair，不要写comparison。'}
    if kind == 'region_objects':
        schema = read_json(Path(__file__).resolve().parents[1]/'assets/schemas/scene.schema.json')
        # Resolve enum from the actual schema, rather than maintaining a second list.
        def field(node, key):
            if isinstance(node, dict):
                if key in node and isinstance(node[key], dict) and 'enum' in node[key]:
                    return node[key]['enum']
                for value in node.values():
                    result = field(value, key)
                    if result is not None: return result
            elif isinstance(node, list):
                for value in node:
                    result = field(value, key)
                    if result is not None: return result
            return None
        return {'image_required': ['id', 'kind', 'bbox', 'asset', 'asset_role', 'source_kind'],
                'element_scope': {
                    'bindings': 'When page scope exists, supply scope_bindings rows with unit_id and local object_ids. Cover each regional unit and every output leaf once. A group binding includes its descendants.',
                    'preserve': 'Preserved raster stays one unchanged source image, using matching user_asset/crop route. reference_artifact requires this binding. No erased text, generated replacement, changed crop or unassigned extra labels.',
                    'edit': 'Required text/geometry/data/group capabilities must exist. Native preserved objects retain their snapshot. Scope classification alone never waives a requirement.',
                    'revision': 'Use page revise with a higher scope revision to correct decisions; regional revisions retain current obligations.',
                    'generation': 'For scoped asset requests include scope_unit_ids; preserve and unresolved units cannot be regenerated.',
                },
                'asset_role_enum': [v for v in field(schema, 'asset_role') if v != 'reference_fullpage'],
                'source_kind_enum': field(schema, 'source_kind'),
                'provenance_required_for': ['generated', 'external'],
                'bbox': {'format': 'xywh', 'units': 'local_reference_pixels'},
                'asset': 'Use an actual available_assets path, or asset-add then next; no guessed file path.',
                'program_fills': ['stable page/region ID prefix', 'editability', 'coordinate conversion'],
                'rotation': 'Object-level field, never style.rotation.',
                'object_revision': ({
                    'action': 'revise_objects',
                    'base_fragment_sha256': context['previous_fragment_sha256'],
                    'required': ['action', 'base_fragment_sha256', 'reason'],
                    'replacements': 'objects and/or components lists of complete replacement records with existing top-level LOCAL IDs; omitted records are retained exactly.',
                    'scope': 'No adding/removing/reordering top-level records. To edit a child replace its entire parent group. Original source_notes, relationship_ids, uncertainties and asset_decisions remain; the response reason records this edit.',
                    'fallback': 'Use the normal complete regional payload when membership, ordering, asset routing or global decisions must change.',
                    'review': 'The entire merged region is validated. New source review, Office render and visual review remain required.',
                } if context.get('previous_fragment_sha256') else None),
                'native_first': context.get('native_first', False),
                'reconstruction_priority': ['current task scope and preservation obligations', 'editable text and numbers', 'draw icons/illustrations first; Agent similarity below 75% permits generation unless the user requires native-only or prohibits generation', 'explicit user generation requests may skip drawing', 'native gradients and per-stop opacity'],
                'raster_required_when_native_first': ['raster_content: '+ '|'.join(field(schema, 'raster_content')), 'reference_artifact requires source-bound preservation scope', 'raster_reason describing the object decision', 'matching asset_decisions entry for every image', 'generated_illustration requires source_kind=generated and generation_decision copied from the accepted asset request'],
                'generation_decision':{'basis':'low_similarity or user_request','reference':'existing project-relative reference file',
                    'drawing':'existing project-relative drawing, required for low_similarity','similarity_pct':'Agent visual judgment 0..100, strictly below 75 for low_similarity',
                    'reason':'local differences or explicit user request; never claim a software measurement'},
                'transparency': 'Alpha is opacity: 0 is fully transparent, 1 is opaque. fill_alpha and line_alpha multiply the corresponding gradient-stop alpha.',
                'references': 'Use complete existing object IDs for cross-object links; duplicate text is not an identity.',
                'asset_decision_fields': ['target_id', 'route', 'generation_considered', 'reason', 'remaining_risk'],
                'asset_decision_routes': sorted(ROUTES),
                'asset_requests': {'single_action':'request_asset','batch_action':'request_assets',
                    'batch_field':'requests','max_items':8,'atomic_request_validation':True,
                    'completion':'Each job keeps its own provenance, permissions and asset_material task. Never replay an accepted batch.',
                    'multi_icon_sheet':'Optional boolean. One transparent PNG may contain separate icons; insert separate source_crop image objects or individually cropped files.'},
                'note': '插图先绘制，再由 Agent 判断相似度；低于 75% 可转入生图，用户明确要求优先。请求带 generation_decision 后软件自动显示默认生图分支，不增加打卡次数。'}
    return {}


def examples(kind, context):
    if kind != 'region_objects':
        return {}
    available = context.get('available_assets', [])
    actual = available[-1]['asset'] if available else '<先asset-add取得真实asset路径>'
    w, h = context['local_size']
    return {'instructions': '先按页面范围合同确认内容归属与编辑要求，再制作当前区域。需编辑的文字保持原生，引用原图按已确认范围保留。以下只示范字段，坐标与内容须重新观察。',
            'native_path': {'id': 'outline', 'kind': 'path', 'closed': True,
                            'commands': [['M',w*.2,h*.8],['C',w*.15,h*.25,w*.7,h*.1,w*.8,h*.8],['Z']],
                            'style': {'gradient': {'type':'linear','angle_deg':0,
                                'stops':[{'position':0,'color':'66AACC','alpha':.3},{'position':1,'color':'225588','alpha':.8}]},
                                'line':'225588','line_width_pt':1}},
            'raster_exception_only': {'id': 'photo', 'kind': 'image', 'bbox': [0, 0, w, h],
                             'asset': actual, 'asset_role': 'photo', 'source_kind': 'crop',
                             'raster_content':'photograph', 'raster_reason':'填写原图中需要保留为照片的具体纹理或连续明暗细节',
                             'fit': 'contain', 'provenance': '填写实际裁切范围与处理方式'},
            'asset_decision': {'target_id': 'photo', 'route': 'crop',
                               'generation_considered': True,
                               'reason': '填写当前对象的实际选择依据，不照抄示例',
                               'remaining_risk': '填写边缘/文字残影/遮挡修补等剩余风险；无则明确写无'},
            'generation_alternative': {'action': 'request_asset', 'request': {
                'id': 'replacement-01', 'purpose': '填写需要替换的局部对象',
                'prompt': '参照局部轮廓、构图和颜色生成独立素材；不带正文、数字、标签。',
                'transparent': True, 'allowed_approximation': True}}}


def validate_asset_decisions(rows, local_ids):
    if not isinstance(rows, list):
        raise ValueError('asset_decisions must be a list')
    seen = set()
    for row in rows:
        keys(row, ['target_id', 'route', 'generation_considered', 'reason', 'remaining_risk'])
        if row['target_id'] not in local_ids or row['target_id'] in seen:
            raise ValueError('asset_decisions target_id must name a unique local object/component')
        seen.add(row['target_id'])
        if row['route'] not in ROUTES or type(row['generation_considered']) is not bool:
            raise ValueError('Invalid asset route or generation_considered type')
        text(row['reason'], 'asset decision reason')
        text(row['remaining_risk'], 'remaining risk')
    return rows
