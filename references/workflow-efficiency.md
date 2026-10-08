# 调用效率与恢复

## 证据校验

同一次调用中，同一路径的同一内容只完整解码一次。每次复用之前仍读取真实文件并计算哈希，缓存只保存格式和尺寸，不保存图片像素或审查结论。调用结束后清空，不建立跨调用通过缓存。

`validation_metrics` 返回哈希、状态校验、图像解码、任务选择和写入的计数与耗时。各阶段存在包含关系，不能相加。`timings` 继续记录授权、代码身份、工作进程和总调用时间。性能比较必须使用同一冻结样本，区分文件系统缓存、Office 渲染和普通审查。

## 提交后继续

`return_next=true` 让提交返回下一项任务。先检查 `submission` 与 `accepted_task`。

| 结果 | 下一步 |
| --- | --- |
| `accepted` | 提交已经保存，处理返回的当前任务 |
| `accepted_next_failed` | 提交已经保存，读取状态和失败阶段，不重放该提交 |
| `not_dispatched` | 请求未派发，按原因修正参数、权限或等待服务恢复 |
| `outcome_unknown` | 先核对状态、回执和进程，禁止自动重试 |
| `rejected` | 查看具体错误；只有原任务仍有效时才修正当前 result |

素材登记会刷新任务身份。前一步失败时，不继续调用依赖其产物的 compare 或 adopt。任务目录存在但没有提交到状态时，工具保留该目录并使用新编号，不采用里面的旧 token。

## 接入与写入锁

`toolbox_context.connection_diagnostics` 和 `toolbox_call_status.diagnostics` 返回当前连接、客户端、bridge 代数、项目绑定、未决调用与写入锁观察。后台存在、配置存在和当前客户端能调用分别判断。

bridge 在升级期间不派发新请求。后端意外退出后保留宿主管道，有限重启后端并通知工具目录变化；已经派发的请求返回结果未知，不重放。恢复后重新绑定项目，过期 context_id 不能继续写入。连续退出达到限制后，需要检查服务并重新连接。

原先已经关闭的宿主连接不能由新程序接管。必须由宿主刷新连接，再通过实际调用确认。

发现进程已经退出的锁，也不能按锁龄自动删除。先核对对应调用回执、状态和任务输出，再显式解锁。不强制结束 PowerPoint，不把未知调用记为成功。

## 编辑与审查

任务字段以当前响应模板和 `submission_constraints` 为准。审查提交使用 passed、needs_changes、blocked，汇总报告的 failed、not_run、not_applicable 不直接用于提交。

`toolbox_project_inspect` 的 scene 操作接受完整 object_id 和明确 set 字段，返回受影响页及区域计划是否仍可验证。它不写文件，不授予新的区域权限。缺少计划时返回页级 revise 步骤，跨区或新增对象需要重新规划。

长图在查看器中被缩小时，需要另外查看原尺寸局部。文字、单位和专名从首版开始核查；移动裁片后检查残字与遮挡。每个观察保留独立文件和结论，不提供默认通过的批量审查。

原生柱体不是数据联动图表。分组需要移动、保存重开检查成员位置；长句替换需要检查换行和越界；数据图表应修改实际数据并确认图形更新。对象数量和编辑回执不替代实际视觉判断。

`office.edit-readback` 对加长的文字补充原生文字边界与文本框比较。
`longer_text_layout` 单独记录边界结果，旋转文字或无法测量的对象保留未验证。
该检查不自动换行、缩字或移动对象，也不代替查看实际渲染。

Office 全页及局部审查任务会返回 `text_geometry_hints`。它使用当前导出回执中的实际文字边界，列出超出文本框或疑似相交的对象及点数。先查看提示对应的局部，再决定如何返修。结果仅供检查，旋转文字、组合内文字、表格单元格及装饰效果可能无法测量；没有提示也不能判定通过。

## 反馈修复后的调用方式

`rebuild_start`、`rebuild_next`、`rebuild_status`、`rebuild_submit` 可选 `response_detail="compact"`。默认仍返回完整任务。精简模式保留任务身份、必看文件、提交约束和素材权限，完整 packet 与 response template 返回路径及 SHA-256。提交前必须读取这些文件，不凭摘要猜字段。`return_next=true` 可与精简模式合用。

`region_objects` 可用 `action="request_assets"` 和 `requests` 数组一次申请 1 到 8 项素材。单项字段仍为 id、purpose、prompt、transparent、allowed_approximation。整批校验通过后才登记，每项继续独立领取 asset_material 任务。已接受的批次不重放；一项完成后，其他项保持 pending。关闭宿主生图权限时，受管入口拒绝登记生成请求。

当前 `material_policy` 带有效值的 `effective_sha256` 及全局、项目版本。工具使用权限与对象编辑要求分别核对。用户改变某对象原生或 PNG 的要求时，按返回的 `plan_update` 用受管 revise 撤回受影响的页或区域，记录原因，再更新页面计划或完整区域的 asset_decisions。旧审查随返修失效，旧计划和交付保留。仅切换工具权限不会自动改写项目内容。

`project_context.initialization_preflight` 会说明目录能否初始化。已有 workflow 应继续原任务；保留目录冲突应换用新目录；遇到初始化锁应先核对恢复信息。预检不会合并、覆盖或删除用户文件。

`icons_search` 默认省略缩略图和审查历史，按需用 `icons_inspect` 查看单项，或显式传 `include_previews=true`。搜索结果仍保留来源与版本。`toolbox_call_status.execution_phase` 可区分模块加载、素材库初始化、检索及描摹；空闲查询不会把自身算成正在执行的工作。小蒙版描摹独立计算，30 秒未完成会停止本次计算。该超时不终止 PowerPoint，也不重放写入请求。

局部文字回归会核对原生对象框与前后 Office 字形边界。实测范围外的变化继续检查，缺失或不支持的测量不能通过自动回归。透明图片在全页和局部审查中增加 `raster_occlusion_hints`，按非透明像素、裁切、放置和层级提示文字交叠；组合、旋转及形状蒙版保留待查，提示不能替代实际看图。

编辑读回的 `content_readback_status` 只说明内容属性是否保存成功。长句越界会返回 `acceptance_status="needs_changes"`；其余情况仍要完成实际视觉检查。附有长句越界回执的 editable_behavior 不能提交为 passed。

## 回归记录

本轮固定案例见 `docs/upgrade/conversation-optimization/regressions.json`。条目连接历史问题和测试，不写入用户经验库，不自动记录用户接受，也不把尚未进行的真实制作标为复发率下降。
