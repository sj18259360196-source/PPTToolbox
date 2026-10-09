"""Bounded work-graph patches. Display metadata never advances production stages."""
from __future__ import annotations

import copy
import re

STATUSES = ('planned', 'running', 'done', 'blocked', 'paused', 'skipped', 'replaced', 'failed', 'outcome_unknown')
STAGES = ('intake', 'plan', 'production', 'revision', 'delivery')
STEP_TYPES = [
    {'id':'intake','title':'任务接入','stage':'intake','actions':['notes','calls']},
    {'id':'analysis','title':'参考图分析','stage':'plan','actions':['files','calls']},
    {'id':'visual_overview','title':'整页主视觉','stage':'plan','actions':['files','calls']},
    {'id':'visual_detail','title':'高清局部','stage':'production','actions':['files','calls']},
    {'id':'plan','title':'制作方案','stage':'plan','actions':['notes','calls']},
    {'id':'text','title':'文字与排版','stage':'production','actions':['preview','calls']},
    {'id':'search','title':'素材检索','stage':'production','actions':['icons','calls']},
    {'id':'material','title':'素材制作','stage':'production','actions':['graphics','icons','calls']},
    {'id':'fidelity','title':'相似度判断','stage':'production','actions':['files','preview','calls']},
    {'id':'generation','title':'AI 生图','stage':'production','actions':['files','calls']},
    {'id':'crop','title':'素材裁剪','stage':'production','actions':['files','calls']},
    {'id':'compose','title':'整页合成','stage':'production','actions':['preview','files','calls']},
    {'id':'preview','title':'导出与预览','stage':'revision','actions':['preview','calls']},
    {'id':'review','title':'核对与修订','stage':'revision','actions':['preview','calls']},
    {'id':'delivery','title':'交付整理','stage':'delivery','actions':['files','calls']},
    *[{'id':kind,'title':title,'stage':stage,
       'actions':['graphics','calls'] if kind=='native_draw' else
                 ['preview','calls'] if kind in {'text_fit','visual_review','detail_review','edit_verify','repair','recheck'} else
                 ['files','calls']} for kind,title,stage in [
        ('requirements','需求与修改范围','intake'), ('resume','恢复上下文','intake'),
        ('region_plan','页面分区','plan'), ('source_text','原文与数字核对','plan'),
        ('route_decision','制作路线决策','production'), ('native_draw','原生图形绘制','production'),
        ('asset_place','素材回装','production'), ('text_fit','文字适配','production'),
        ('visual_review','整页视觉核对','revision'), ('detail_review','局部细节核对','revision'),
        ('edit_verify','编辑与读回验证','revision'), ('feedback','用户反馈','revision'),
        ('revision_plan','修改范围判断','revision'), ('repair','局部返修','revision'),
        ('recheck','返修复查','revision'), ('recovery','异常诊断与恢复','revision'),
        ('reproducibility','重建与复现验证','revision'), ('acceptance','等待用户确认','delivery'),
    ]],
]
RELATIONS = ('dependency', 'sequence', 'decision', 'merge', 'revision', 'suggested', 'grouping')
LINK_SCHEMA = {
    'type':'object', 'additionalProperties':False, 'required':['from','relation'],
    'properties': {
        'from':{'type':'string','pattern':'^[a-zA-Z0-9_-]{1,64}$'},
        'relation':{'enum':list(RELATIONS)},
        'label':{'type':'string','maxLength':120},
        'basis':{'enum':['recorded','agent','inferred','suggested']},
        'evidence_ids':{'type':'array','maxItems':12,'uniqueItems':True,
                        'items':{'type':'string','minLength':1,'maxLength':160}},
    },
}
NODE_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['id'],
    'properties': {
        'id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,64}$'},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 80},
        'kind': {'enum': [t['id'] for t in STEP_TYPES]},
        'status': {'enum': list(STATUSES)},
        'after': {'type': 'array', 'maxItems': 12, 'uniqueItems': True,
                  'items': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,64}$'}},
        'detail': {'type': 'string', 'maxLength': 1500},
        'result': {'type':'string','maxLength':600},
        'next_action': {'type':'string','maxLength':600},
        'round': {'type':'integer','minimum':1,'maximum':999},
        'links': {'type':'array','maxItems':12,'items':LINK_SCHEMA},
        'task_ids': {'type':'array','maxItems':12,'uniqueItems':True,
                     'items':{'type':'string','minLength':1,'maxLength':160}},
        'evidence_ids': {'type':'array','maxItems':12,'uniqueItems':True,
                        'items':{'type':'string','minLength':1,'maxLength':160}},
        'stage': {'enum': list(STAGES)},
        'tools': {'type': 'array', 'maxItems': 12, 'uniqueItems': True,
                  'items': {'type': 'string', 'minLength': 1, 'maxLength': 120}},
    },
}
PATCH_SCHEMA = {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': NODE_SCHEMA}


def merge(previous, patches, *, source, at):
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(PATCH_SCHEMA).iter_errors(patches))
    if errors:
        raise ValueError('工作图字段无效，请提供步骤编号及变更内容')
    identifiers = [p['id'] for p in patches]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('同一次更新不能重复提交步骤编号')
    nodes = {n['id']: copy.deepcopy(n) for n in (previous or {}).get('nodes', [])}
    for patch in patches:
        identifier = patch['id']
        template = next((t for t in STEP_TYPES if t['id']==patch.get('kind')), {})
        if identifier not in nodes and not patch.get('title', '').strip() and not template:
            raise ValueError('新增步骤需要 title')
        if 'title' in patch and not patch['title'].strip():
            raise ValueError('步骤名称不能为空')
        node = nodes.get(identifier, {'id': identifier, 'status': 'planned', 'after': []})
        if template:
            node.setdefault('title', template['title'])
            node.setdefault('stage', template['stage'])
        if 'after' in patch and 'links' not in patch and 'links' in node:
            node['links']=[link for link in node['links'] if link['from'] in patch['after']]
        node.update(copy.deepcopy(patch))
        node.update(source=source, updated_at=at)
        nodes[identifier] = node
    if len(nodes) > 64:
        raise ValueError('每个项目的工作图最多保留 64 个步骤')
    # Check the complete merged graph, including references from untouched nodes.
    for node in nodes.values():
        if node['id'] in node['after'] or any(p not in nodes for p in node['after']):
            raise ValueError('前置步骤不存在或连接到了自身')
        parents = [link['from'] for link in node.get('links', [])]
        if len(parents)!=len(set(parents)) or any(p not in node['after'] for p in parents):
            raise ValueError('连线说明必须唯一且对应 after 中的前置步骤')
    pending = {identifier: set(node['after']) for identifier, node in nodes.items()}
    visited = set()
    while pending:
        ready = [identifier for identifier, parents in pending.items() if parents <= visited]
        if not ready:
            raise ValueError('工作图存在循环；返工请新增步骤并保留旧路径')
        for identifier in ready:
            visited.add(identifier)
            pending.pop(identifier)
    return {'format': 'ppttool-work-graph/1', 'nodes': list(nodes.values()), 'updated_at': at}


def diagnostics(nodes):
    """Non-blocking display advice; never turns missing metadata into a failed task."""
    parents = {p for n in nodes for p in n.get('after', [])}
    return [{'node_id':n['id'], 'message':'后续关系尚未登记，可连接到预览、复查或交付；如已结束，请补充结果。'}
            for n in nodes if n['id'] not in parents and n.get('stage')!='delivery'
            and n.get('source')!='visual_telemetry' and n.get('status') not in {'skipped','replaced'}
            and not n.get('result')]
