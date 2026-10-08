# 多页制作与修订

多页制作调用 rebuild_submit 时设置 return_next=true。CLI 使用 submit --return-next。直接处理返回的 task，只有没有返回任务、需要查询状态或处理失败时再调用 next。accepted_task 表明提交已完成，即使后续领取失败，也不能重放这次提交。工具按原有权限执行，未自动填写审查结论。

调用结果和 call.json 的 timings 分别记录授权检查、代码身份检查、未决调用检查及子进程等待。累计调用时长包含等待，不等于可节省的净计算时间。

validation_metrics 补充图片读取、哈希、解码、状态验证和下一步领取的次数与耗时。
同一次调用可复用相同内容的图片解码结果，每次使用仍重新读取并核对哈希。
各阶段可能相互包含，耗时不能简单相加。恢复状态与字段约束见 workflow-efficiency.md。

toolbox_project_inspect 接受明确的 project 路径。action=identity 返回 project_root、project_id 和 workbench_key。复盘接口也接受已登记路径和项目 ID，歧义或身份不一致时拒绝。

action=scene 对当前场景或已授权 scene 文件执行只读预检。changes 使用完整 object_id 和 set 字段，支持明确的几何、文字和样式修改。不会补造 evidence、静默删除悬空引用或改写原文。报告 valid 后仍须通过受管 patch 或 replace-scene 应用修改。

impact 按变化页说明对象、原区域计划是否可验证以及是否需要重新规划。
变化页须重新观察，返回预检通过不代表视觉验收通过。

移动或缩放对象后，只要对象身份集合、原区域计划和坐标映射仍可验证，且对象没有越出授权区域，即可保留局部修改合同。新增或删除对象、改变坐标系或跨区域修改需要重新规划。缺少原始计划时，使用明确的页级 revise 重新领取计划，不能修改 state 绕过。

工具仅对整页对象、主题、共享素材和 Office 对照图均一致的页面关联旧视觉观察。关联记录保留 source_run 和原始记录，交付时重新校验。变化页、编辑行为和重建验证仍按新任务完成。Agent 不得自行填入旧 passed。

action=views 按 offset 和 limit 返回当前任务必看文件的哈希、尺寸和路径。生成文件、收到索引或缩略图均不代表已看图。出现输出截断时重新按小批次打开，提交时只列实际查看的文件。

action=scene 可设置 scan_crops=true，按图片索引 offset 和 limit 检查疑似文字行。该本地启发式会漏检或把纹理识别为文字，不执行 OCR，不识别文字内容。crop_findings 返回素材像素区域，warnings 同时提供可能的图片遮挡。移动、缩放或重裁素材后，对照原素材与 Office 渲染检查残字、页码和正文，工具不会自动擦除。

正式安装的 agent_bridge 保持宿主标准输入输出连接，升级期间暂停派发，后端恢复后通知工具目录更新。不会重放写入或恢复过期 context_id，恢复后重新 bind 再查 status。旧版已经关闭的宿主连接无法由新程序接管，需宿主重新连接一次；后续连接才使用新守护入口。安装中断留下的更新标记须先核对安装日志和备份，不自动清除。
