# 局部试制与增量编辑

四个接口共用原管理服务、worker、policy、项目锁及日志。原六接口和正式门禁保留。测试状态以第二阶段VALIDATION现行摘要为准，本页说明合同，不代替验收。

| MCP | 受管CLI工具ID | 输入概要 |
|---|---|---|
| rebuild_probe | workflow.probe | project、operation_id、task_id、base_revision、result；office可选，默认true |
| rebuild_patch | workflow.patch | project、operation_id、base_revision、scene_sha256、pptx_sha256、slide、region、changes、reason |
| rebuild_compare | workflow.compare | project、operation_id、trial_id |
| rebuild_adopt | workflow.adopt | project、operation_id、trial_id、comparison_id、observation |

JSON Schema由tools/list及toolbox_manager/contracts.py给出。未知字段、非法类型、非有限数值和自由操作名均拒绝。CLI使用 `--project <精确项目> --request <授权JSON文件>`；JSON包含相应MCP参数但不包含project，不能借文件重定向项目。

试制只接受当前region_objects任务的实际objects/components，复用区域局部px到原canvas的换算，不消耗token、主revision或正式候选。试制维持整页物理比例，输出reference-region.png、fragment、scene、可编辑PPTX和按需Office收据。整页其余区域可以未完成。缺Office保留样件，不自动填写审查结论。

同一区域最多6个probe/patch意图，失败尝试也计数。operation_id只能包含字母、数字、下划线或连字符，最长40字符。相同ID及内容只读回既有结果；不同内容、旧版本、改变的输出被拒绝。中断且没有完成记录时返回outcome_unknown，不自动重做。

## 补丁范围

| op | 字段 | 当前支持边界 |
|---|---|---|
| text.set | id、text | 未旋转顶层原生单段单run文本；拒绝显式富文本与换行 |
| text.style | id、style | 字号pt、RGB颜色、left/center/right、四侧margin_*_pt；未指定属性保留 |
| geometry.set | id、bbox | 普通文本框、形状、独立图片；bbox为原scene逻辑xywh，图片需stretch或明确source_crop |
| fill.set | id、color | 普通不透明原生形状；六位大写RGB，拒绝渐变/透明填充 |
| group.translate | id、delta | 已有无缩放无旋转的单层组，delta为scene逻辑单位；子对象及顺序保留 |
| picture.crop | id、source_crop | 顶层独立图片，stretch或已有source_crop；输入为原素材像素xywh，保留媒体和蒙版 |

带效果/阴影、任意组缩放旋转、嵌套组、图表/表格编辑不在本阶段补丁范围。请求只能选择已有page.plan区域内稳定ID，不提供allowed_ids扩权。移动后对象仍须落在区域内。

后端仅改现有PPTX指定slide部件，保留原文件；PowerPoint实际保存关闭重开并独立读回。更新scene的整页重建是额外一致性验证，不是补丁后端。坐标容差0.01pt，裁切分数0.00001，不代表视觉容差。

## 对照与采用

参考图对照与原候选前后回归分开。范围外结构比较保留对象全文XML、层级、顺序；仅忽略creationId/modId元数据，另记录原始部件差异。像素遮罩取已授权叶对象新旧边界的并集，加实际线宽的一半及固定2px抗锯齿边缘；组外接矩形不替代叶对象范围。范围外通道阈值和允许变化比例均为0，环境不一致不算通过。

Agent实际查看compare返回的全页及局部文件，提交observation的status、note、reviewer和viewed_files。允许needs_changes采用后继续审查；硬错误、范围外变化或scene/PPTX不一致不能采用。程序不能代写观察。

probe采用进入原submit链，patch采用以一次原子state写入绑定新scene/PPTX，清除旧任务与审查。旧候选、失败记录及交付均保留。采用不等于交付，仍经原source/full/local/edit/reproduction门禁及finish。

Office操作按同一管理目录的office-writer.lock串行。发生超时需先核对工作流、worker和Office占用，不自动清锁，不终止用户PowerPoint。独立管理目录及绕过管理器的脚本不受该队列协调。公开事件只记ID、字段名、数量及哈希；结果原文和token保留于受控项目/运行目录。
