# 工具箱 Agent 协作

项目页面分开显示当前制作状态和历史调用诊断。已交付不代表用户认可；旧失败不直接覆盖当前交付状态。搜索无匹配属于正常结果，当前写入缺少终态时继续提示待核对。

矢量项目的共享工作台按所选候选显示制作、检查与交付，PPT 等待、当前 worker、助手摘要和备注另列全项目当前观测。管理助手可读取事实和受管文件、核对摘要、保存备注及交接材料，记录独立于制作状态。不支持矢量工作图编辑、Office、场景预检、阶段打卡和 adopt。选择明确项目作用域后才能保存备注或管理候选；摘要沿用已有连接与预算，旧来源或旧备注对应的摘要不能当作当前结论。详细范围见[助手自动记录](assistant-recording.md)和[矢量空间](vector-space.md)。

下文阶段上下文、工作图批次、场景与 `.ppttool/assistance` 机制均适用于 PPT 项目。

制作 Agent 从 stage_context.assistance_packet 读取当前任务、交付、待核对项和证据编号。先使用现有交接信息，只在证据不足时查询详细日志。不为整理记录增加逐工具打卡或重复看图。

内置 Agent 共二十六个接口，包含原有七个管理接口、十个辅助接口和九个批量记录接口。read_call_details、inspect_artifact 和 assess_issues 读取项目证据；prepare_handoff、prepare_review_bundle 准备管理候选；validate_scene_candidate 复用图形预检；record_issue_disposition 只记录程序允许的历史处置。run_registered_checks 仅支持 project_records 和 delivery_files。draft_experience_update、draft_tool_change 保存带真实证据的更新候选。批量记录接口见[助手自动记录与补图](assistant-recording.md)。

上述十个接口属于内置 Agent 的工具集，不是新增的制作 MCP 工具。制作 MCP 继续使用现有入口。辅助候选保存在项目 .ppttool/assistance，附项目版本和输入指纹。项目变化后重新读取，不将旧候选自动应用到新版本。

Responses Agent 开启时，后台按保存频率集中更新工作图、摘要和备注；前台管理任务和后台整理使用不同工作线程，共用原有预算与权限。大阶段上下文提供确定性交接包，外部模型不可用时仍可使用本地状态。

场景导入与 graphics_scene_preflight 共享预检。1.1 场景必须声明 `path_base=project_root`，reference、asset 和 drawing 从明确绑定的项目根目录解析；1.0 场景继续按场景文件目录解析。导入前通过 `toolbox_project_inspect` 的 `action=scene` 核对实际文件、缺失项及越界，不按同名文件猜路径。缺失 evidence 必须提供真实来源，不自动伪造。调用结束回执先保存再返回宿主；宿主断开后仍需核对记录，不重放未知写入。

经验和工具更新候选通过验证后进入项目默认能力的源码与构建流程。候选不直接覆盖程序、PPT 或验收结果。用户已停用的工具、项目授权和素材权限继续生效。
