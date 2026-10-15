"""Canonical production preferences, independent of manager and tool permissions."""
from __future__ import annotations
import copy
import hashlib
import json

DEFINITIONS = [
    {'key': 'overlay_checking', 'label': '叠图检查', 'default': 'standard', 'control': 'switch',
     'description': '每页首次全页校验查看叠图。之后用于精确定位、指定区域和大幅布局变化。频繁检查会增加审查工作，具体元素的精度要求保持独立。',
     'options': [{'value': 'standard', 'label': '标准检查', 'description': '首次全页必查，之后按需使用。'},
                 {'value': 'frequent', 'label': '频繁叠图检查', 'description': '每个新版本的全页和必查局部都查看叠图，未变化的有效观察可复用。'}]},
    {'key': 'illustration_mode', 'label': '插画制作', 'default': 'generate_first',
     'description': '简单图标继续使用原生对象。复杂插画按所选方式制作，具体对象要求优先。',
     'options': [{'value': 'generate_first', 'label': '图片生成优先', 'description': '复杂插画优先生成独立高清素材，需要透明时保留真实透明底。'},
                 {'value': 'draw_first', 'label': '可编辑绘制优先', 'description': '优先拆分和绘制原生形状或路径，提供内部路径编辑。'}]},
    {'key': 'font_matching', 'label': '字体匹配', 'default': 'similar',
     'description': '文字准确、可编辑且布局稳定。精细匹配会增加字体检索与比对工作。',
     'options': [{'value': 'similar', 'label': '相近字体优先', 'description': '使用本机风格与字重接近的字体。'},
                 {'value': 'precise', 'label': '精细匹配', 'description': '以参考中的相同文字渲染候选，比较字形、宽度、基线与换行。'}]},
    {'key': 'text_layout', 'label': '文本框组织', 'default': 'paragraph',
     'description': '不跨栏、卡片或语义区域合并。两种方式都检查溢出与布局。',
     'options': [{'value': 'paragraph', 'label': '段落优先', 'description': '同一段文字保存在一个文本框，方便整句修改并保留局部样式。'},
                 {'value': 'line', 'label': '逐行优先', 'description': '按参考行位分别定位，各行可独立调整并按段落分组。'}]},
]
DEFAULTS = {row['key']: row['default'] for row in DEFINITIONS}


def defaults():
    return dict(DEFAULTS)


def validate_values(values, partial=False):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise ValueError('Unknown production setting fields')
    # Read historical three-field snapshots without changing their evidence hash.
    if not partial and values.keys() not in (DEFAULTS.keys(), DEFAULTS.keys() - {'overlay_checking'}):
        raise ValueError('All production setting fields are required')
    for row in DEFINITIONS:
        if row['key'] in values and values[row['key']] not in [item['value'] for item in row['options']]:
            raise ValueError('Invalid production setting ' + row['key'])
    return dict(values)


def instructions(values):
    if values is None:
        return ['沿用原项目策略。用户应用制作设置后，再通过正式修订更新受影响任务。']
    values = validate_values(values)
    illustration = ('复杂插画优先参考生成独立高清素材。已有完整干净主体可复用。服务不可用时尝试适用绘制，无法满足要求时说明缺口并请用户决定替代。'
                    if values['illustration_mode'] == 'generate_first' else
                    '复杂插画优先语义拆分、钢笔节点或选区转路径。交付实际原生对象或路径，位图嵌入 SVG 不能作为内部编辑完成。能力不足时说明差距并请用户决定图片替代。')
    font = ('优先使用本机风格与字重接近的字体，保证文字准确、可编辑及布局稳定。'
            if values['font_matching'] == 'similar' else
            '标题与关键字形精细匹配。用参考相同文字渲染本机候选，比较字形、字重、宽度、基线和换行，并在 Office 核对。未知字体找不到时记录候选与差异，正文保留可编辑。')
    text = ('同一语义段落优先放入同一原生文本框，以 paragraphs 和 runs 表达局部样式。截图自然换行不自动拆框。'
            if values['text_layout'] == 'paragraph' else
            '按参考行位组织原生文本框，并按语义段落分组。检查各行和整体移动后的溢出与对齐。')
    overlay = ('每个新版本的全页和必查局部查看叠图，未变化的有效观察可复用。'
               if values.get('overlay_checking') == 'frequent' else
               '每页首次正式全页校验查看叠图，检查移位、比例和大幅偏差。之后按需用于精确定位、指定高要求区域和大幅布局变化。')
    return [illustration, '简单线性、粗线条和少量规则形状组成的图标始终原生绘制，页面背景与主体分开。具体对象的最新明确要求优先。', font, text, overlay,
            '叠图重影须回到左右图确认具体缺陷。截图噪声、抗锯齿和要求允许的生成纹理差异不单独触发返修。每次返修说明对象、问题与预期改善；同一问题连续两轮无改善时选择换方法、接受允许差异或保留未解决状态，没有新缺陷就停止追加检查。',
            '独立标题、标注与可单独移动的项目保留独立对象。禁止跨栏、跨卡片、跨语义区域合并，表格图表保留结构。',
            '制作偏好不授予素材服务、上传、付费或文件权限。保留原件与身份准确要求继续按具体对象执行。']


def snapshot(values=None, revision=0, source='default'):
    values = validate_values(defaults() if values is None else values)
    if type(revision) is not int or revision < 0:
        raise ValueError('Production revision must be a nonnegative integer')
    return {'values': values, 'revision': revision, 'source': source,
            'effective_sha256': hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'instructions': instructions(values)}


def definitions():
    return copy.deepcopy(DEFINITIONS)
