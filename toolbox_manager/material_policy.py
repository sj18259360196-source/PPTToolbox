"""Owner preferences for host material tools; never grants filesystem access."""
from pathlib import Path
from .project_context import ProjectContext

FIELDS = {'material_search_allowed': '联网查找素材', 'host_generation_allowed': '使用生成图片',
          'reference_upload_allowed': '上传必要参考局部'}


def effective(manager, project=None):
    import hashlib,json
    from scripts.material_routes import GUIDANCE, THRESHOLD
    overrides = {}; revision = manager.settings()['revision']
    if project:
        root = str(ProjectContext(manager, project).root)
        record = manager.store.get('material_policy:' + root, {})
        overrides = record.get('values', {}); revision = record.get('revision', 0)
    values = {k: overrides.get(k, manager.settings()[k]) for k in FIELDS}
    return {'values': values, 'global_values':{k:manager.settings()[k] for k in FIELDS}, 'overrides': overrides, 'revision': revision,
            'global_revision':manager.settings()['revision'],
            'effective_sha256':hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest(),
            'plan_update':{'tool':'rebuild_revise','required_when':'The user changes the editability or asset route of a page/object.',
                'instruction':'Keep prior plans and the user reason. Use slide-level revise to update page planning, or region-level revise and a full region payload to update asset_decisions. Affected prior reviews must be renewed. Tool permission alone does not change object editability.'},
            'scope': 'project' if project else 'global',
            'illustration_route':{'threshold_pct':THRESHOLD,'comparison':'strictly_below',
                'assessor':'production_agent','scope':'individual_illustration_not_whole_page',
                'instruction':GUIDANCE,'record':'request.generation_decision',
                'work_graph':'accepted requests add drawing, assessment, generation, optional crop and placement nodes'},
            'services': '使用宿主当前已配置、可调用的服务；能力是否可用由宿主确认',
            'spending': '不自动购买额度或开通新的付费服务',
            'instruction': '这些值是用户持久授权。在允许范围内直接执行，不重复请求同意。当前用户的明确限制优先。'
                           '上传仅限任务必要参考局部，不扩大到无关资料或未经许可的新服务。'
                           '生成图标记为示意，不冒充真实人物或历史照片。工具不可用时报告能力缺失。'
                           '工具箱偏好不能替代宿主自身的权限检查。'}


def save_project(manager, body):
    from .workbench import Workbench
    import json
    root, _, _ = Workbench(manager).entry(body.get('project'))
    values = body.get('values')
    if not isinstance(values, dict) or values.keys() - FIELDS.keys() or any(type(v) is not bool for v in values.values()):
        raise ValueError('素材权限字段无效')
    key = 'material_policy:' + str(root)
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        record = json.loads(old[0]) if old else {'revision': 0}
        if body.get('revision') != record['revision']: raise ValueError('权限已更新，请刷新后重试')
        db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps({'revision': record['revision'] + 1, 'values': values})))
    manager.store.event('material.policy.saved', '已保存项目素材权限', details={'project':str(root)})
    return effective(manager, root)
