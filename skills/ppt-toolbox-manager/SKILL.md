---
name: ppt-toolbox-manager
description: 管理PPT工具箱的Skill、工具与指令、插件、设置、离线版本和日志；用管理器读取当前受管上下文。PPT制作继续使用捆绑的重建核心。
---

# 工具箱管理

制作任务按返回的 view_strategy 选择看图范围，整页用于布局，原始像素局部用于制作和找错。相同 task_id 与图片哈希在当前上下文中已查看时继续工作，无需重复开图。提交使用 return_next=true；上下文变长时保存发现，从 HANDOFF、status、next 接续，仅补看当前必要图片。工具保留完全未变页面的有效原图核对记录，旧记录缺少内容绑定时需重新核对。Office、视觉和编辑验收仍按当前任务执行。详细约定见 ../../references/multipage-efficiency.md。

软件提供后台窗口、项目列表、工作台和受管调用日志，PPT 分析、制作与验收由 Agent 配合工具完成。启动、目录和迁移以[当前软件说明](../../references/current-desktop.md)为准。

先解析本Skill目录链接的真实目标，再从真实目录向上两层找到包根目录 `manager.py`，不要从未解析的Windows目录链接计算父目录。使用当前Python执行：

```text
python "<真实根目录>/manager.py" --data-dir "<当前MCP使用的数据目录>" context
python "<真实根目录>/manager.py" --data-dir "<当前MCP使用的数据目录>" check
python "<真实根目录>/manager.py" --data-dir "<当前MCP使用的数据目录>" serve
```

MCP已配置时先用 `toolbox_context`，按需调用 `toolbox_search`、`toolbox_describe`、`toolbox_manual`。
运行路径按任务自动归类。需要表达决策、汇合或用户反馈后的返修时，在已有阶段打卡的 `flow` 中批量更新，优先使用 `step_types`，不足时每批补一到两个自定义节点。分支要接回合成、复查或交付；返修另建轮次，保留旧路径。只提交有依据的关系，推断和建议显式标明，不为绘图增加看图或制作重试。字段与示例见[项目运行路径](../../references/project-work-graph.md)。
联网搜图、生图、上传必要参考局部，读取 `toolbox_material_policy` 或当前上下文的 `material_policy`。允许值是已保存的用户授权，不逐次询问；项目例外和用户当前明确限制优先。宿主未提供所需工具时说明能力缺失，不再要求用户同意同一操作。
MCP未加载时先核对宿主注册的 command 和 args。独立安装通常使用随包 runtime/python.exe 与 portable.py；显式数据参数或 location.json 决定实例，不要求注册必须包含 manager.py 或 --data-dir，也不默认与旧软件共用数据。
无 MCP 时使用 `manager.py describe --tool <ID>` 读取工具详情及 `managed_argv_prefix`；保留返回的管理器解释器与数据目录。
根工具箱的 start/next/submit 等流程使用对应的 workflow.* 注册项，经返回的 managed_argv_prefix 调用。
受管执行需要用户在管理器开启。禁止绕过用户停用决定直接使用旧副本。

若受管 Python 工具报 `No module named common`，先核对当前管理器是否包含 `toolbox_manager/python_entry.py`；该入口负责把受管脚本的兄弟模块纳入搜索路径。不要把工具故障回执填成成功。桌面软件退出提示出现时请用户重新打开管理器，读取状态再继续；不能借直接脚本跳过启停要求。真实故障与局部返修见运营渠道案例（本地验收记录未随包提供）。

管理器启停作用于受管入口及其已覆盖的内部工作流步骤，不是系统级沙盒。直接运行未受管脚本不受该权限层限制。
PowerShell 设置会传给受管子进程及内部 Office 渲染；未配置时优先使用固定安装位置的 PowerShell 7，再查 PATH。等待退出码标记为 action_required，原始退出码保留在返回结果中。
用户指令覆盖由 context/manual 接口读取，不自动改写原始Skill或其他宿主副本。
MCP 入口以当前 tools/list、schema 和发行清单为准，不从旧版数量推算。`rebuild_start/next/submit/status/revise/finish` 复用受管 CLI 服务；局部操作、技能、路由和校准也走同一权限及日志。`next` 和 `finish` 可推进构建与 Office 导出，有实际写入。其他工具仍使用受管 CLI。MCP 不提供生图、任意命令、安装、开执行开关或目录授权工具。

首次工作先读取 toolbox_context，核对 instance.data_dir 与用户窗口的数据目录一致。使用返回的 entry_argv 或已注册 MCP，不复用历史命令中的旧数据目录。`settings.auto_approve_project_requests` 开启时，直接调用受管 start，由工具箱应用用户保存的自动批准策略并继续创建。关闭时，未授权请求由用户在项目页批准或拒绝。已拒绝项目保持拒绝；手动批准后重新核对状态，再继续原请求。不得伪造任务或重试未决副作用。Agent 不自行执行 authorize-project 或修改授权开关。内部构建、检查、Office 导出、对照和交付步骤仍检查受管能力。

start 的目标目录必须尚不存在。先保存图片时用工作目录下的 input，目标项目用同级尚不存在的 project 子目录。不要先创建目标项目目录，再调用 start。已有 workflow/state.json 时读取 status 并续作；只有素材文件夹时不能宣称制作项目已启动。

结构化参数、错误/等待、超时恢复和日志边界见[受管执行](../../references/managed-execution.md)。发生 `outcome_unknown` 时先 `rebuild_status` 观察真实状态及日志，不重复执行先前的有副作用操作。任务 `token` 只留在受控任务记录和协议响应，不复制到公开日志。

多页提交使用 `return_next=true`。`accepted_task` 表明提交已保存，后续失败按 `recovery` 处理，不重放。任务审查使用 passed、needs_changes、blocked。接入诊断、调用内校验和局部修改影响见[调用效率与恢复](../../references/workflow-efficiency.md)。

第二阶段增加 `rebuild_probe/patch/compare/adopt`，沿用同一服务、policy、worker和日志。实际参数见[局部重建合同](../../references/local-rebuild.md)。对应CLI为workflow.probe/patch/compare/adopt，使用授权request JSON，不能传自由argv或COM属性。局部证据不自动继承为整页passed。当前实施与测试状态见 `docs/upgrade/phase-02/STATUS.json`。

请求安装时先运行 register-codex 查看计划；取得用户确认后才用 --apply。
新增有界校准入口为rebuild_calibrate_plan/step/report，经同一受管服务执行。plan冻结参数和预算，step由程序选数值，report不渲染。详见[有界校准](../../references/calibration.md)，当前验收见docs/upgrade/phase-03/STATUS.json。不得把评分推荐写成视觉通过。
以 register-codex 返回的计划为准。它只登记本地插件来源，不改 config.toml，
也不等于插件已安装。另行执行 codex mcp add 才会登记MCP并修改宿主配置。
两种接入方式分开验证，不能把来源登记当成实际PPT验证通过。
不要扫描其他插件、API密钥或对话记录。不要为了日志而修改用户PPT项目。

日常任务使用独立于checks的管理数据目录，MCP与界面必须使用同一 `--data-dir`。
新版支持后台桌面与托盘；受管调用成功后自动登记项目，列表可分类及归档。
独立包使用随包Python和data目录，不从旧安装目录读取依赖。接入后核对
context.active.path及distribution，不能凭同名Skill或版本号推断运行身份。
接入与产品形态见[本机接入状态](../../manager_docs/AGENT_INTEGRATION.md)。
