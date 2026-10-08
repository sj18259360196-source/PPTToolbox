# 原生插画的拆层与调用

这套方法适用于需要编辑瓶体、包装、软管、衣物和水珠等部件的参考图重建。先确认物品轮廓和遮挡，再用路径、渐变和独立高光表达材质。绘图配方输出原生对象，Agent 仍需依据参考决定各个轮廓和层的用途。

## Agent 的制作顺序

1. 看整页，固定卡片、物品区域、正文和重叠次序。原文中的缩写和符号逐一保留。
2. 为每个实物写出识别轮廓和部件清单。先完成外形与主要明暗，缩回页面尺寸检查辨识度，再添加细节。
3. 每个材质层指定用途。透明物品分别处理空孔、半透明表面和亮边；金属用窄亮带与相邻暗带；织物先保留衣形，再处理局部褶皱。
4. 规则纹理用有界重复。绕弯的连续曲面共用中心线。不规则瓶肩、帽口和透视盒沿按参考拟合。
5. 编组保持卡片、物品、部件三级。短 ID 表达部件用途，正文保持文字对象。不可辨认的印刷小字仅重建可见纹理，不编造内容。
6. 先看透明预览和白底预览，再回装受管候选。使用实际 Office 导出检查全页与相关局部，抽样改字、改色、移动分组，并从持久 scene 复现。

以上记录可核查的决策依据与操作顺序。无需输出逐字内部推理。

## 一条中心线生成多层曲面

先调用 `graphics_inspect`。只有返回的 `capabilities` 含 `surface_layers`，且当前 schema 包含对应模式，才提交此配方。旧版可以读取本手册和经验，不能假定已支持新字段。

完整示例在 [native-tube.json](../examples/graphics/native-tube.json)。这是可编辑多层软管的通用配方。中心线是隐藏的开放路径，生成后的七个闭合曲面保留在同一组内。

```json
{
  "id": "tube",
  "mode": "surface_layers",
  "source": "centerline",
  "tolerance": 0.05,
  "layers": [
    {"id": "body", "width": 8, "offset": 0,
     "style": {"fill": "BED0DC", "fill_alpha": 0.8, "line": null}},
    {"id": "highlight", "width": 1.04, "offset": -2.32,
     "style": {"fill": "FFFFFF", "fill_alpha": 0.65, "line": null}}
  ]
}
```

这一段是完整配方中的一个 `curve_groups` 项。完整请求将配方放在 `recipe`，并将当前已授权项目路径放在 `project`。

| 参数 | 含义 |
|---|---|
| width | 当前局部坐标中的层宽，至少 0.12 单位 |
| offset | 沿路径方向的左法向位移，改变中心线方向会翻转正负侧 |
| tolerance | 偏移曲线拟合容差，范围 0.01 至 2；实际值还受层宽约束 |
| layers | 从后到前排列，每层独立 ID 和样式，最多 16 层 |
| style.gradient | 手工填充渐变支持 2 至 16 色标；拟合器仍最多拟合 5 色标 |

该实现复用现有有界偏移与曲线拟合，连接两侧边界形成平端曲面。检查退化段、截断端点和采样后的自交；不能通过时返回错误。输出采用有界偏移和曲线拟合。

层次相交需要按物理遮挡拆成前后段。管口的椭圆与空腔另建对象；中心线反向后要重新检查高光方向。函数不自动计算灯光、折射或材质，也不保证任意紧弯均可生成。失败时缩小层宽、减少偏移或拆分曲线，保留原草稿供对照。

## 实际工具调用

| 用途 | MCP 或受管工具 | 输入与结果 |
|---|---|---|
| 查经验 | experience.search | 追加查询词，如 `软管 中心线 七层` |
| 读完整经验 | experience.show | 使用当前检索返回的经验编号 |
| 读原文 | experience.source | 使用当前条目的来源编号与行号；每次最多 80 行 |
| 看合同 | graphics_inspect | 读取 schema、capabilities 和 illustration_example |
| 看草稿 | graphics_preview | `recipe`；输出中间预览 |
| 编译草稿 | graphics_compile | `project` 与 `recipe`；返回版本、目录、objects |
| 局部提交 | rebuild_submit | 当前 context_id、task_id、token、result 与 return_next=true |
| 真实编辑 | office.edit-readback | 按 describe 的当前输入文件合同编写编辑操作 |
| 分组移动恢复 | office.group-roundtrip | 按当前合同提供分组完整 ID、位移及容差 |
| 复现 | pptx.build、office.render | 从持久 scene 重建到新目录，再核对结构与实际导出 |

表里的点号工具 ID 通过 `toolbox_describe` 获取当前 `managed_argv_prefix`。保留返回的解释器和管理数据目录，然后追加参数。MCP 名称与注册工具 ID 不混用。接口返回 `accepted_task` 后，按下一任务或 recovery 继续，不能重复提交已接受写入。

编译对象用于当前 `region_objects` 任务时，确认配方使用同一局部裁图坐标。路径直接使用命令坐标，shape/text 的 bbox 为 xywh，页面分区遵守当前 schema。`font_size_pt` 与 `line_width_pt` 已经是点值，不再次乘像素比例。返回 objects 放入当前结果的 objects，其他必需字段按当前任务合同补齐。

旧案例删掉 path/group 的多余 bbox 后提交成功。复用时先用当前验证接口定位字段错误，再仅删掉该对象类型确实不接受的派生字段，保留 shape/text 的尺寸。

## 怎样使用指令库

指令区提供五份新模板。它们只在对应任务出现时引导 Agent，读取 context 不会触发绘图或改变项目授权。

| 指令名称 | 使用时机 | 应得到的结果 |
|---|---|---|
| 原生插画先拆物品与材质 | 开始复杂插画 | 带物品、识别轮廓、材质层及前后关系的制作方案 |
| 共用中心线绘制多层软管 | 弯管、电缆或带状高光 | 经当前合同验证的配方与原生草稿 |
| 透明材质、透孔与金属反光 | 包装和容器 | 独立表面、孔与高光，并检查目标背景 |
| 原生插画回装与字段核对 | 区域提交前或字段报错后 | 坐标、分组及 schema 一致的区域对象 |
| 原生插画编辑与复现检查 | 候选完成后 | 同版本视觉、编辑及复现记录 |

模板正文保存在 `assets/experience/knowledge/command-recipes.json`。加入当前管理器后会出现在 `toolbox_context.instructions`。不要把历史路径、旧 task token、历史通过结论作为新任务的参数或验收。

## 验证范围

几何与原生包测试不代替实际 Office 渲染与编辑读回。需要分别检查全页、局部、材质改色、分组移动和持久 scene 复现。公开仓库不附带个人经验原文，相关检索需要先导入自己的经验。
