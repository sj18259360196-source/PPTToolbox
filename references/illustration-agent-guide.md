# 插画重绘的 Agent 调用指南

1.26.7 提供直接 MCP 入口 graphics_illustration_guide。启动 context 的 agent_capabilities.illustration、制作任务提示、工具目录和图形构造页均可找到。无需先读经验库，也无需寻找案例里的 Python 文件。

## 先读取当前接口

调用 graphics_illustration_guide，参数可用空对象。route 可选 overview、pen、selection。返回方法判断、按路线排列的步骤、各工具当前 input_schema、required_fields、enabled 状态和 managed_argv_prefix。这个入口只读取说明，不制作 PPT，执行总开关关闭时仍可读；单独停用此工具后拒绝调用。

```json
{"route":"selection"}
```

toolbox_describe 的 id 使用 graphics.illustration_guide。其他 graphics 与 icons 工具的 describe 同样返回当前 input_schema。CLI 以返回的 managed_argv_prefix 为准，追加 --json 和请求 JSON 文件路径。涉及项目的 graphics 操作明确传 --project 完整路径；icons 的项目字段按其当前 schema 填写，不追加不支持的参数。

指南返回的是参数装配说明，template_status 为 requires_real_inputs_not_ready_to_execute。必须根据已查看参考图填写观察、部件、颜色规则、路径和实际 SHA-256。执行权限、项目授权与单工具开关继续分别校验。调用中断先查状态与日志，不能因没有看到结果就重放。

## 方法判断与绘制顺序

先看整页确定视觉重点和区域关系，再查看当前必要的原始像素局部。在 page_plan.notes 简记部件、方法和依据；不额外增加逐对象分析任务。

| 当前观察 | 方法选择 | 下一步 |
| --- | --- | --- |
| 少色填充、语义部件可分、边界清楚 | 钢笔节点或选区转路径 | 先试关键局部，再决定按部件混用 |
| 尖角、细枝、多孔、混色边 | 优先钢笔节点；选区只做局部试验 | 固定关键锚点并核对孔洞与连接 |
| 渐变、透明边和亮边 | 几何与材质分开处理 | 先定轮廓，再做原生填充与透明度 |
| 照片、纹理或明确折面 | 不使用曲线平滑路线 | 按编辑要求和素材权限另选表达 |
| 边界、部件归属不明确 | 暂不判断 | 补看必要局部，未知项不填肯定 |

调用 graphics_route_illustration 保存实际观察与建议。工具不自动识图，Agent 必须依据当前图判断。用户明确要求原生可编辑时，不能用整张位图替换。

## 钢笔与节点路线

1. 拆分语义部件、白色绘图和透明孔洞。先完成主要轮廓与叠放关系。
2. 分段绘制路径。在极值、尖角、切线转折和连接位置设置锚点，平滑段少放节点。不要用一条路径强行包住所有空白与部件。
3. 原始片段保存为项目内 UTF-8 JSON，计算文件哈希。调用 graphics_fit_paths，传入当前观察、公差及必要的 anchors。
4. 整条共用闭环可调用 graphics_share_rings。部分共边用配方 edges/faces 明确边 ID 和方向，不分别拟合后声称它们共边。
5. 根据误差位置调整锚点、部件归属和公差。变圆、节点变少均不能单独作为改善依据。

## 选区转路径路线

1. 用 graphics_freeze_evaluation 根据原图冻结评价掩膜、采样方式、比例和哈希，保留至少一个明确口径。不得随候选调整真值。
2. 对单个语义部件调用 graphics_selection_masks。color 使用明确颜色规则；edge_assisted 只做轻度增强辅助；coverage 依赖局部前景背景假设，渐变或多色交界可能失效。
3. 检查 selection.png 的孔洞、连通、细枝和误选。expected_topology_mismatch 或 adoption_blocked 必须先处理，孔数相同也不等于语义正确。
4. 将 trace-black-foreground.png 编码为 data URL，传给 icons_trace_fragment.mask。box 使用源图坐标，不能按采样放大后的尺寸填写。先保留 smoothing=none、simplify_error_px=0 的基线；引擎仍会描摹，不能声称零误差。
5. 从实际返回值提取 scene_fragment 单独保存，再计算其哈希并调用 graphics_fit_paths。不要将完整工具响应当作片段输入。共享环按需处理，处理后重新测量。
6. 几何轮廓、内部颜色和亮边分开调。白色形状与透明孔使用各自的语义表示。

## 验证与迭代

graphics_evaluate_stages 在同一参考框测量选区、描摹、拟合、共边和 Office 阶段，pairs 明确阶段对。graphics_compare_regions 单独检查内部颜色和未匹配区域。不能把阶段指标相减当因果，不能自动配准后掩盖位置偏差。

逐轮记录实际查看的部位、问题、修改和结果。主观轮廓、孔洞细枝、颜色、编辑成本可分别估计 0 到 100 并写依据；机器 IoU、双向距离、内部 RGB 误差、节点数另列。不合成一个自动验收总分。

孔洞丢失或连通改变时先修选区；轮廓过圆或偏移时修关键锚点与公差；颜色不对时调整填充。每轮只改主要因素。连续两轮无改善则重新选择方法。合理评价口径排名反转时保留两稿，回看原始局部后决定。有限像素和抗锯齿无法唯一恢复原始矢量，百分之百重合不能作为无条件承诺。

最终通过当前 region_objects 或 rebuild_probe/patch/compare/adopt 合入候选，继续完成真实 Office 渲染、原始像素局部核对、编辑动作、保存重开及 scene 复现。工具结果不自动通过这些门禁。

## 软件中的入口

打开素材库中的图形构造页，在少色分层插画重绘区选择方法，点击读取调用指南，再复制给 Agent。切换方法后需重新读取，避免复制旧路线。展开当前参数与步骤可以检查完整结果。按钮只读指南，不自动执行绘图。

工具页可搜索 graphics.illustration_guide，查看受管入口；指令页仍保留用户模板及启停状态。用户覆盖旧说明时不会被升级静默覆盖，动态启动指令和 context 的结构化能力入口继续提供本版指南。安装升级后，原有 MCP 会话需重连才能发现新增工具。

详细算法边界和案例见 references/layered-illustration.md。经验 EXP-207、EXP-208、EXP-209 为补充材料，直接调用不依赖经验检索。
