"""Small, explicit visual-context advice; never records a visual observation."""
from pathlib import Path
from PIL import Image
from common import sha256


def strategy(project, packet):
    kind = packet['kind']
    local = kind in {'region_objects', 'asset_material', 'review_local', 'preview_local'}
    items = []
    for rel in packet['required_view_files']:
        path = Path(project) / rel
        with Image.open(path) as im:
            size = list(im.size)
        items.append({'path': str(path.resolve()), 'sha256': sha256(path),
                      'file_bytes': path.stat().st_size, 'pixel_size': size,
                      'role': 'local_detail' if local else 'page_layout' if kind == 'page_plan' else 'page_review',
                      'detail_if_downscaled': max(size) > 2048})
    result = {
        'scope': 'local' if local else 'whole_page', 'required': items,
        'required_file_bytes': sum(item['file_bytes'] for item in items),
        'measurement_scope': 'Local encoded files only; not API payload bytes or request latency.',
        'decision': ('先看当前高清局部。需要判断跨区对齐、层级或连线走向时补看整页；细节仍不清楚时按对象边界裁切。'
                     if local else '整页用于理解布局。文字、数值、细线和遮挡看不清时，按语义区域补看原始像素局部，再作审查结论。'),
        'detail_tool': 'assets.crop source output --box left top right bottom',
        'detail_coordinates': 'Crop source-image pixels; use packet reference_size and region bbox for scene coordinates.',
        'repeat_policy': '同一 task_id 和图片哈希在当前上下文中已实际查看且仍可辨认时，直接继续制作或提交观察。重复 next 不代表新任务。上下文丢失后重新查看必要图片。',
        'quality_rule': '缩略图不能证明细节通过。补看局部不替代当前 must_view_files；只提交实际查看且覆盖要求的观察。',
        'continuation': '对话变长时保存当前工作与发现，从项目 HANDOFF、status 和 next 接续，按当前任务取图，不重新读取历史图片目录。',
    }
    if packet.get('context',{}).get('whole_page'):
        result['optional_whole_page']=str((Path(project)/packet['context']['whole_page']).resolve())
        result['original_reference_size']=packet['context'].get('reference_size')
    return result
