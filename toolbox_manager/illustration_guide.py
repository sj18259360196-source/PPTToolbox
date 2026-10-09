"""Direct, read-only method discovery built from current managed contracts."""
from __future__ import annotations
import copy

GUIDANCE = '遇到少色分层插画，先调用 graphics_illustration_guide 读取判断条件、步骤和当前参数，再根据实际看图填写 graphics_route_illustration。可按部件选择钢笔节点或选区转路径。读取指南不依赖经验检索；模板必须补齐真实观察、路径和哈希，生成候选仍遵循项目授权。'
ROUTES = {
 'pen': [
  ('graphics.route_illustration','根据实际观察判断适用性，未知项保持未知'),
  ('graphics.freeze_evaluation','仅按原图冻结评价口径，不能追着候选改参考'),
  ('graphics.fit_paths','先分语义部件绘制路径，固定尖角、极值、连接和孔洞锚点，再有界拟合'),
  ('graphics.share_rings','仅在需要时复用完整闭合环，部分共边使用配方 edges/faces'),
  ('graphics.evaluate_stages','同框测量原始绘制、拟合和最终候选，明确阶段对'),
  ('graphics.compare_regions','单独核对共同内部颜色和未匹配区域')],
 'selection': [
  ('graphics.route_illustration','确认少色区域可分离，记录渐变、细枝、多孔和多色混边风险'),
  ('graphics.freeze_evaluation','先冻结原图评价口径和哈希，再制作候选'),
  ('graphics.selection_masks','按语义部件选色；边缘增强仅辅助选区，保留原图'),
  ('icons.trace_fragment','将返回的黑前景蒙版按原图坐标转路径，基线 smoothing=none、simplify_error_px=0'),
  ('graphics.fit_paths','保存描摹片段为项目内 JSON 并计算哈希后，有界拟合'),
  ('graphics.share_rings','可选复用整环；核对孔洞、绕向、细缝和共享边'),
  ('graphics.evaluate_stages','比较选区、描摹、拟合和 Office 输出，排名反转时保留候选复查'),
  ('graphics.compare_regions','检查内部颜色、亮边及不匹配区域')],
}
def entry(manager):
 p=manager.package()
 return {'tool':'graphics_illustration_guide','arguments':{},
         'enabled':bool(p['enabled'] and p['trusted'] and manager.override(p['id'],'tool','graphics.illustration_guide',True)),
         'read_only':True,'requires_experience_lookup':False,'instruction':GUIDANCE,
         'manual':'references/illustration-agent-guide.md'}

def guide(manager,args):
 from .graphics import SPECS
 from .icons.contracts import SPECS as ICONS
 route=args.get('route','overview')
 selected=ROUTES if route=='overview' else {route:ROUTES[route]}
 available={r['id']:r for r in manager.catalog()}
 steps={}
 for key,rows in selected.items():
  steps[key]=[]
  for tid,purpose in rows:
   family,op=tid.split('.')
   schema=copy.deepcopy((SPECS if family=='graphics' else ICONS)[op][1])
   tool=manager.tool(tid)
   steps[key].append({'tool':tid.replace('.','_',1),'tool_id':tid,'purpose':purpose,
     'enabled':available[tid]['enabled'],'requires_execution_enabled':True,
     'input_schema':schema,'managed_argv_prefix':tool['managed_argv_prefix'],
     'cli_tail':['--json','<project-contained-request.json>'],
     'argument_assembly':{'required_fields':schema.get('required',[]),
       'project':args.get('project','<authorized-project>') if 'project' in schema.get('properties',{}) else None},
     'template_status':'requires_real_inputs_not_ready_to_execute'})
 return {'format':'illustration-agent-guide/1','entry':entry(manager),'route':route,
   'execution_enabled':manager.settings()['agent_execution_enabled'],
   'classification':[{'when':'少色填充、语义层清楚、边界可分离','choose':'selection 或 pen，按部件试验'},
    {'when':'尖角、细枝、孔洞多或颜色混合边','choose':'pen；必要时局部 selection 并复核拓扑'},
    {'when':'照片、纹理、明确折面','choose':'不套用本曲线方法，按素材约束另选表达'},
    {'when':'未看清或语义未知','choose':'补看必要原始像素局部后重新判断'}],
   'steps':steps,'handoff':[
    '每步使用实际返回的文件和哈希；JSON 片段单独存项目内，不能把完整工具响应当 scene_fragment',
    'trace_fragment.mask 使用黑前景图像的 data URL；box 使用源图像素，不能使用放大采样尺寸',
    'share_rings 只复用完整闭环；部分共边使用 graphics 配方 edges/faces',
    '保留旧轮次，每轮只改主要误差来源；孔洞/连通变化先修选区，过圆或位移先修锚点与公差',
    '连续两轮无改善重新选择方法；合理口径排名反转时检查原始局部和颜色，不自动挑最高分',
    '最终片段进入当前 region_objects 或 rebuild_probe/patch/compare/adopt，再完成 Office 渲染、保存重开、编辑读回和 scene 复现'],
   'assessment':{'subjective':'轮廓、孔洞细枝、颜色与编辑成本分别估计 0 到 100，附已查看的局部和理由',
    'measured':'IoU、双向边界距离、内部颜色误差、节点数分列，不合成验收分',
    'limit':'有限分辨率原图与抗锯齿不能唯一确定原始矢量，不能承诺百分之百重合'},
   'automatic_execution':False,'automatic_visual_approval':False}
