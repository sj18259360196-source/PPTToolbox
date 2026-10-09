# 少色分层插画的两条制作路线

保留钢笔与节点迭代、选区转路径两条路线。制作 Agent 先看整页及必要的原始像素局部，调用 graphics_route_illustration。在 page_plan.notes 简记对象或部件、实际观察、所选方法与理由。工具根据 Agent 提交的观察提供建议，不自动识图，也不自动采用候选。旧 observations 字段继续有效；没有填写的新特征保持未知。

| 观察 | 可选方法与下一步 |
| --- | --- |
| 少色填充、区域可拆、共享边明确 | 可试选区转路径，同时保留钢笔路线 |
| 渐变、亮边或内部颜色变化 | 分别选择几何和材质方法，可按部件混用 |
| 细分支、多孔、三色混合 | 先做代表局部，覆盖率假设失效时改钢笔节点 |
| 部件归属或边界不明确 | 补看局部后判断，不把缺省值当观察 |
| 孔洞丢失或连通结构变化 | 拒绝采用该候选，修选区或换路线 |
| 合理评价口径下排名反转 | 保留两稿，核对局部、颜色和编辑成本 |

用户的原生编辑和素材约束优先。照片、纹理、明确折面应采用匹配的表达，不套用曲线平滑。

## 通用选区与冻结参考

graphics_freeze_evaluation 只接受原图及 SHA-256、评价比例和 policies，不接受候选。每个策略有 name、sampling 和 rules。sampling 选择 nearest_binary 或 bilinear_field，分别表示原图先二值化再最近邻采样、原图标量场双线性采样再阈值化。rules 中 weights 对应 R、G、B 的线性权重，min/max 为严格边界。固定像素中心、比例、阈值和原图哈希，先冻结再选择候选。每次输出新文件，不能追着候选改真值。

graphics_selection_masks 接收相同原图身份、method 和 rules，可选 scale、support_mask 与对应哈希、源图坐标 seeds、expected_topology。method 可为 color、edge_assisted、coverage。前两种分别直接按颜色分区、轻度边缘增强辅助分区；增强图不取代原图作为几何依据。coverage 另需 foreground_rules、background_rules、coverage_weights，可选 minimum_contrast、coverage_threshold、clip_rules。局部二色混合估计在渐变、亮边和多色交界可能失效。

工具返回白前景 selection.png 和黑前景 trace-black-foreground.png、源图尺寸、采样比例、孔洞与连通分量，topology_changed 或 expected_topology_mismatch 时标记 adoption_blocked。这里与直接颜色选区的比较只提供风险信号，真实语义仍需看图。禁止把相同孔数理解为拓扑或语义已经完全正确。

先逐语义部件生成显式选区。support_mask 和 seeds 由已观察的部件给出，不内置人物坐标。孔洞和白色绘图分别处理。经 icons_trace_fragment 转路径时，box 保持源图坐标范围，不能按采样后尺寸扩大。先保存 smoothing=none、simplify_error_px=0 的描摹稿。该设置仍经过描摹引擎，不能宣称输出与像素边界零误差。

## 路径、共享边和材质

graphics_fit_paths 接收项目内 UTF-8 JSON、input_sha256、observations 和可选 rms、max_error、anchors。锚点按路径 ID 指定，公差使用输入坐标单位。输出独立 scene_fragment 与采样距离报告，不修改输入。拟合失败保留原路径；它不保证减少节点，也不纠正错误选区。开放路径保留，开放路径锚点拒绝。

graphics_share_rings 在同一个 source_pixels 坐标系复用整条闭合轮廓。relations 指定 source、target、source_ring、target_ring 及可选 reverse；max_displacement 限制采样位移。源轮廓来自调用前快照，避免顺序造成级联变化。工具检查目标绕向、单路径嵌套与自交，保留样式，重复目标拒绝。它不会猜测哪些边应当共用。

部分共享弧使用现有 graphics 配方的 edges/faces，明确边 ID 和方向，经 graphics_preview/compile 验证。不要用两个独立拟合结果冒充共享曲线。共边处理后重新测量，前一次拟合报告不能用于最终结果。graphics_fit_gradient 及原生渐变负责材质；白色绘图保留原生部件，真正透明孔保持孔洞语义。

## 分阶段测量与返修

graphics_evaluate_stages 读取冻结 contract_file 与哈希，各 stage 指定 id、显式二值 mask 和 SHA-256。所有掩膜必须与冻结评价框完全一致，工具不自动配准或归一化包围框。pairs 明确比较 from/to，可用于选区对描摹、描摹对拟合、数值路径对 Office 的直接测量。阶段指标不能相减或相加解释因果。rankings 仅列 IoU 排序，ranking_reversal 要求复查，automatic_winner 恒为空。

颜色用 graphics_compare_regions 的同框内部 RGB 误差另测，保留未匹配区域。graphics_compare_contours 返回原始边界距离和叠图，质心对齐数据仅供诊断，不能替换原始距离。新版轮廓测量支持受管 CLI 的 project 字段，数值计算在独立子进程中进行，避免读取 MCP 协议输入。

逐轮根据实际错误只改一个主要因素。轮廓更圆、节点更少或 IoU 更高，都不足以自动采用。记录关键部位、孔洞、细缝、颜色、亮边和编辑成本；主观各项 0 到 100 估计附理由，与机器指标分列，不合成验收总分。连续两轮没有改善时重新选方法或明确剩余问题。

## 案例与验证边界

两轮孕妇案例表明，选区拟合可以改善一种冻结采样口径下的轮廓，但在另一合理口径下排序可反转；旧钢笔稿颜色更好且节点更少。脑形覆盖率实验丢孔并改变细分支，作为失败样本保留。方法不能由单例推广成全图自动胜出。

这些工具要求当前项目授权及执行开关，返回候选与证据，不替代 rebuild 的实际 Office 渲染、原始像素核对、指定编辑动作、保存重开和 scene 复现。原交付和失败轮次保留，未经采用不替换。全部新输入输出位于项目内，文件带哈希，拒绝越界、过期输入和资源超限；outcome_unknown 先核对结果，不重放。

## 入口示例

先用 toolbox_describe 读取当前 schema 和 managed_argv_prefix。CLI 显式给出 --project 完整路径与 --json 请求文件。工具没有默认的孕妇颜色阈值，下面仅示范字段形式。

```json
{"project":"<authorized-project>","reference":"input/crop.png","reference_sha256":"<sha256>","method":"color","rules":[{"weights":[1,-1,0],"min":45}],"scale":1}
```

只在已经查看当前图并确认适用时使用这些参数；参数来自某一颜色特征，不能盲用于其他图。闭合共享环对应 graphics_share_rings，部分共享弧继续使用配方边关系。经验 EXP-207、EXP-208 与 EXP-209 分别说明原拟合、双路线选择和独立评价。


## 1.26.7 插画方法直接入口

少色分层插画先调用 graphics_illustration_guide，按实际观察选择钢笔节点或选区转路径，再调用 graphics_route_illustration。指南直接返回当前参数、受管调用入口、步骤和复查条件，不依赖经验检索。保留孔洞与共享边，分别验证轮廓、颜色和编辑行为。详见 [Agent 调用指南](../references/illustration-agent-guide.md)。软件图形构造页可读取并复制整套调用步骤；升级后重连 MCP。
