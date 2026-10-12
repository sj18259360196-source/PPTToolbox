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
        if context.get('production_settings'):
            from workflow_production import REVIEW_SCHEMA, review_required
            result['production_settings'] = context['production_settings']
            result['production_instructions'] = context.get('production_settings_instructions',[])
            if review_required(context['production_settings']): result['production_review_schema'] = REVIEW_SCHEMA
        if context.get('material_quality'):
            from material_quality import REVIEWS
            result['material_reviews_schema'] = REVIEWS
            result['material_reviews'] = 'Review every material_quality unit. Copy its current output_sha256, record separate independence/edges/fidelity/resolution observations and unresolved defects. Evidence rows bind actual viewed image files by sha256 and role. Independent or transparent materials need light, dark and target backgrounds, plus comparison; review_full also needs office. Alpha or editability alone cannot pass fidelity. Preserve legitimate white labels, internal arrows, gradients and fades.'
        if kind in {'review_full','preview_full'}:
            result['required_checks'] = ['visual_full','raster_scope','text_geometry']
        if kind in {'review_local','preview_local'}:
            result['relationship_ids'] = context.get('relationships', [])
        if kind == 'source_review':
            from material_text_review import CHECK_SCHEMA
            result['material_text_checks_schema'] = CHECK_SCHEMA
            result['material_text_checks'] = 'For generated images with declared readable text, view the actual current image and provide object_id, asset_sha256 and observed_text strings in declaration order. Exact text and punctuation must match for passed. Preserved source photos do not need this generation text check.'
            result['element_scope'] = {
                'required_when_present': 'scope_review with current revision and every source unit exactly once; each row has unit_id, status, note.',
                'review': 'Inspect original source and task requirement independently. Check ownership, omitted text, preserved artifacts and conflicting evidence. A declared label or digest is not semantic proof.',
                'completion': 'Unresolved units forbid passed. Every native text object needs exact text_checks. Inspect image titles and embedded readable text in the actual image through material_text_checks and scope_review; correct metadata alone cannot pass. Tables and chart labels require source review even without separate text objects.',
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
            if context.get('independent_materials'):
                result['material_edit_coverage'] = 'For every independent_materials root object record required edit_tests named material_move, material_resize and material_backgrounds; material_replace for compositions containing pictures. Save/reopen actual copies and inspect light/dark/target backgrounds. Native groups may contain opaque internal labels. Picture changes must also exist in attached PPTX copies.'
        return result
    if kind == 'page_plan':
        from element_scope import SCOPE
        from material_quality import CONTRACT, REQUIREMENT
        return {'element_scope_schema': SCOPE,
                'production_settings':context.get('production_settings'),
                'production_instructions':context.get('production_settings_instructions',[]),
                'preserved_regions':context.get('settings_preserved_regions',[]),
                'material_quality_policy': context.get('material_quality_policy'),
                'material_contract_schema': CONTRACT, 'material_requirement_schema': REQUIREMENT,
                'material_qualification': 'New reference workflows require material_contract for illustrations, preserved raster and photographs. Save the exact user requirement as UTF-8 under input; cite file, sha256 and verbatim excerpt, independently of task_requirement summary. Give every material a material_requirement. Page screenshot clarity and lack of internal editing are not evidence of an independent asset. Background/route constraints follow the cited user text; preservation needs a qualifying source or explicit user/photo/identity basis. Keep original references on revision; append a new source when the user changes requirements. This binds evidence, not automatic semantic interpretation.',
                'element_scope_guidance': [
                    'For newly authored plans include element_scope version 1 and revision 1. Legacy plans remain readable. On replan retain stable source IDs and increment revision.',
                    'Read the user task before assigning required_edit. Record task_requirement and each unit requirement, semantic_role, input_form, owner_id, evidence and counterevidence. Do not infer scope from OCR or object kind alone.',
                    'Cover every region and all source content, including uncertain candidates. Use unresolved for a genuine conflict; never drop an obligation to obtain a pass.',
                    'A cited poster may require preserve; an explicit request to edit that same poster requires text. Full-slide text screenshots do not qualify for automatic preservation.',
                    'Separate semantic ownership from geometry, draw_order and production order. Analyze whole page then modules; keep existing back-to-front assembly.',
                    'Record content_type, material_route and text_ownership on the same source unit. Use current production_settings. simple_icon is a line/geometric icon and stays native; simple_illustration is not automatically native. generate_first directly generates illustrations unless an independent clean asset is reusable; draw_first preserves internal path editing. Existing assets describe provenance, not mandatory preservation. Photograph fidelity and explicit user constraints decide preservation or reference generation.',
                    'Keep photograph or illustration embedded text with its owning material; OCR detection alone does not make it standalone page text. Record readable original text in embedded_text. Leave unreadable text empty and never invent it. Page text stays native; internal artwork editing requires an explicit requirement.',
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
        from material_routes import DECISION_SCHEMA, GUIDANCE
        from asset_batch import BATCH_ITEM_SCHEMA
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
        from material_quality import REVIEWS
        return {'production_settings':context.get('production_settings'),
                'production_instructions':context.get('production_settings_instructions',[]),
                'image_required': ['id', 'kind', 'bbox', 'asset', 'asset_role', 'source_kind'],
                'material_reviews_schema': REVIEWS,
                'material_reviews': 'When the scope has material_contract, include one material_reviews row per regional material before placement. Inspect standalone output and reference comparison; provide sha256-bound light/dark/target views for independent or transparent components. output_sha256 is optional here and issued by the controller for subsequent source/Office review. Open defects cannot pass. After revise_objects supply fresh material_reviews instead of silently retaining old observations.',
                'element_scope': {
                    'bindings': 'When page scope exists, supply scope_bindings rows with unit_id and local object_ids. Cover each regional unit and every output leaf once. A group binding includes its descendants.',
                    'preserve': 'Preserved raster stays one unchanged source image, using matching user_asset/crop route. reference_artifact requires this binding. No erased text, generated replacement or unassigned extra labels. Only source-bound photographs may declare material_requirement.display with exact crop/mask/fit; other preserve contracts retain their existing limits.',
                    'edit': 'Required text/geometry/data/group capabilities must exist. Native preserved objects retain their snapshot. Scope classification alone never waives a requirement.',
                    'revision': 'Use page revise with a higher scope revision to correct decisions; regional revisions retain current obligations.',
                    'generation': 'For scoped asset requests include scope_unit_ids; preserve and unresolved units cannot be regenerated.',
                    'text_ownership': 'Keep material-owned text in that material, with readable original text constrained and reviewed. Standalone page text stays native. No erasure, duplicate overlaid text or per-character edit test for preserved/replaceable material text.',
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
                'native_first_meaning': 'Compatibility flag for raster source/routing checks, not a requirement to redraw every material as native geometry. Component content and required_edit govern the route; internal illustration editing requires an explicit request.',
                'reconstruction_priority': ['current task scope, component ownership and preservation obligations', 'native standalone page text and numbers', 'follow current illustration_mode for artwork; generate_first has no compulsory drawing or score; draw_first requires editable paths', 'native line/geometric simple_icon in both modes', 'inspect photograph fidelity and independent existing-asset qualification', 'native gradients and per-stop opacity'],
                'raster_required_when_native_first': ['raster_content: '+ '|'.join(field(schema, 'raster_content')), 'reference_artifact requires source-bound preservation scope', 'raster_reason describing the object decision', 'matching asset_decisions entry for every image', 'generated_illustration requires source_kind=generated and generation_decision copied from the accepted asset request'],
                'generation_decision_schema': DECISION_SCHEMA,
                'generation_decision':{'basis':'content_category, user_request or legacy low_similarity','reference':'existing project-relative reference crop',
                    'content_category':'permits illustration/title, qualified photo or existing artwork with image_replace/group; exact-source constraints still forbid regeneration',
                    'drawing':'required only for legacy low_similarity; no mandatory native trial for content_category',
                    'similarity_pct':'optional except legacy low_similarity, which remains strictly below 75; never invent a score',
                    'text_ownership':'asset_title or embedded permits only current material-owned text; page text remains native',
                    'embedded_text':'readable exact original text; unreadable text is empty; decorative_title requires asset_title ownership and readable original text; review actual output through material_text_checks and scope_review',
                    'reason':'component category and edit requirement, local comparison, or explicit user request'},
                'transparency': 'Alpha is opacity: 0 is fully transparent, 1 is opaque. fill_alpha and line_alpha multiply the corresponding gradient-stop alpha.',
                'references': 'Use complete existing object IDs for cross-object links; duplicate text is not an identity.',
                'asset_decision_fields': ['target_id', 'route', 'generation_considered', 'reason', 'remaining_risk'],
                'asset_decision_routes': sorted(ROUTES),
                'asset_requests': {'single_action':'request_asset','batch_action':'request_assets',
                    'batch_field':'requests','max_items':8,'atomic_request_validation':True,
                    'completion':'request_assets creates separate jobs with their own asset_material tasks. For one host sheet use request_asset with request.items; each item keeps its own reference, crop, provenance and retry state. Never replay an accepted task.',
                    'multi_icon_sheet':'Optional boolean for legacy sheets. For one generation sheet associated with multiple components, set true and supply request.items.',
                    'sheet_items_schema':{'type':'array','items':BATCH_ITEM_SCHEMA,'minItems':1,'maxItems':8},
                    'sheet_completion':'request.items is one host sheet call. Start with 2..8 independent items; a remaining retry can contain one item. Actual item crops have stable id, integer crop xywh, accepted/retry, note and actual viewed_files, bound to sheet_sha256. Accepted is crop selection only; final visual review remains required. Retry only unfinished items.'},
                'note': GUIDANCE}
    return {}


def examples(kind, context):
    if kind != 'region_objects':
        return {}
    available = context.get('available_assets', [])
    actual = available[-1]['asset'] if available else '<先asset-add取得真实asset路径>'
    w, h = context['local_size']
    return {'instructions': '先按页面范围合同确认内容归属与编辑要求，再制作当前区域。页面独立文字保持原生，照片与插画内部文字随素材保留；复杂插画和装饰标题按组件要求选择独立素材。以下只示范字段，坐标与内容须重新观察。',
            'native_path': {'id': 'outline', 'kind': 'path', 'closed': True,
                            'commands': [['M',w*.2,h*.8],['C',w*.15,h*.25,w*.7,h*.1,w*.8,h*.8],['Z']],
                            'style': {'gradient': {'type':'linear','angle_deg':0,
                                'stops':[{'position':0,'color':'66AACC','alpha':.3},{'position':1,'color':'225588','alpha':.8}]},
                                'line':'225588','line_width_pt':1}},
            'photograph_with_explicit_fidelity': {'id': 'photo', 'kind': 'image', 'bbox': [0, 0, w, h],
                             'asset': actual, 'asset_role': 'photo', 'source_kind': 'crop',
                             'raster_content':'photograph', 'raster_reason':'填写原图中需要保留为照片的具体纹理或连续明暗细节',
                             'fit': 'contain', 'provenance': '填写实际裁切范围与处理方式'},
            'asset_decision': {'target_id': 'photo', 'route': 'crop',
                               'generation_considered': True,
                               'reason': '填写当前对象的实际选择依据，不照抄示例',
                               'remaining_risk': '填写边缘/文字残影/遮挡修补等剩余风险；无则明确写无'},
            'reference_generation': {'action': 'request_asset', 'request': {
                'id': 'replacement-01', 'purpose': '填写需要替换的局部对象',
                'prompt': '参照局部轮廓、构图和颜色生成独立素材；保留所属素材内部可辨识原文，页面独立正文与外加标签在 PPT 中制作。',
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
