# 项目工作链与大阶段打卡

项目列表读取管理数据库中的登记索引，只显示文字。新增、归档、改名、排序、层级或交付状态变化后才更新列表，不定时遍历全部项目文件，也不自动统计空间。点击项目名称进入详情，按需读取该项目的工作链和当前 PPT。空间管理在点开后统计。

项目内部以 `.ppttool/events/` 中的不可变事件保存事实，`.ppttool/state.json` 是可恢复的当前状态。`ppttool.md` 只提供可读说明，自动记录区之外保留需求与人工备注。项目身份可从结构化记录恢复，不依赖 MD 文件存在。子文件夹中独立登记的项目具有独立身份和工作链，界面用可展开目录和面包屑导航呈现。

通过软件或受管 Agent 新建的项目会自动登记。外部移动文件夹或导入旧目录后，在项目页点扫描文件夹恢复索引；同时存在的相同项目身份会报告冲突。后台按工具事件采集有变化的项目，进入项目后持续采集当前项目。全局数据库中的目录索引可重建，项目内的事件与文件保持独立。

手动顺序保存在管理数据库，子项目在同一上级内调整。归档项目及其成品只出现在已归档页，成品页显示未归档项目的成品。未登记的启动申请可以单独或批量归档，归档后须由用户恢复再继续启动。详见 manager_docs/PROJECT_MANAGEMENT.md。

## 制作 Agent 的六次登记

| 时机 | event | stage |
| --- | --- | --- |
| 接到任务，确认需求 | begin | intake |
| 开始制定制作方案 | transition | plan |
| 开始主体制作 | transition | production |
| 主体完成，开始整理修订 | transition | revision |
| 开始整理交付文件 | transition | delivery |
| 交付文件完成 | finish | delivery |

从受管 `rebuild_start` 的 `stage_context` 获取 `run_id` 与 `phase_revision`。首次 `rebuild_next` 可同时携带以下 `checkpoint`。也可以独立调用 `toolbox_checkpoint`，再加上 `project` 参数。

```json
{
  "checkpoint_id": "intake-001",
  "run_id": "从当前 stage_context 读取",
  "expected_revision": 0,
  "event": "begin",
  "stage": "intake",
  "result_summary": "已收到参考图和可编辑要求",
  "next_action": "检查输入并制定页面方案",
  "artifact_refs": [],
  "used_experiences": []
}
```

后续使用返回的 `next_revision`。同一登记遇到网络重试时保留 `checkpoint_id` 和原始内容，软件会去重。版本冲突时调用 `toolbox_project_activity` 读取最新状态，再决定下一步。不要盲目覆盖。

正常流程共六次登记。阶段内的 next、submit、构建、渲染和文件变化由软件观察，无需再汇报进度。可把 checkpoint 合并在 rebuild_next 或 rebuild_submit 中；打卡记录与工具调用结果分别保存，工具失败不会撤销已登记的计划。

改道用 `replan`，保留原分支并返回当前或更早阶段。等待外部条件时用 `blocked` 并填写 `blocker`；暂停用 `pause`，继续用 `resume`。这些异常登记只在情况发生时提交。阶段不得跳过，不需要做实质修订时可在切换结果中说明原因。finish 需要项目内交付文件相对路径；文件未出现时界面显示产物待确认。

软件至少检查首次接单登记和交付前的阶段位置。制作 Agent 负责在中间大阶段真实切换时登记，软件不会根据某一次页内工具调用猜测整个项目已经进入下一大阶段。此前的项目保留原流程，从首次打卡起建立工作链。

## 软件关闭或 API 不可用

MCP 打卡不依赖 PPTAgent API。软件界面关闭时仍可通过受管 MCP 保存记录。MCP 暂时不可达时，可把相同结构的 JSON 原子写入 `.ppttool/checkpoints/pending/<checkpoint_id>.json`，重新打开软件后读取 `.ppttool/checkpoints/receipts/` 的收件结果。只提交自己已获得授权的项目，不填写其他项目路径。冲突保留待核对，不覆盖既有阶段。

## 经验使用

每次阶段登记返回最多三条相关经验，没有合适条目时返回空列表。查阅触发条件、操作与限制，按实际问题采用。下一次打卡的 `used_experiences` 填写实际采用的 EXP 编号。推荐次数、Agent 报告采用和当前结果是不同证据；任何推荐或采用计数都不自动表示方法有效。

项目页只显示当前 PPT 的基本预览和打开文件入口，不提供历史版本下拉框。优先使用已确认交付文件或当前制作候选，历史文件保留在项目中，需要时交由 Agent 查找。预览来自与当前 PPTX 哈希一致且成功的渲染记录，文件变化后重新匹配。这里不读取或展示 PPT 元素检查、叠加图和对比面板。制作工具内部必要的审查与交付要求仍按当前工具合同执行。

左侧 Agent 接入配置驻留 PPTAgent 的 Responses API 地址、模型和 Key。保存后可测试一次工具调用及结果回传；启用后，项目变化触发后台摘要。Key 由 Windows 加密保存。Chat Completions 仅保留辅助摘要兼容。

PPTAgent 可查询项目、读取记录、检索经验、查询待办、按已有规则处理申请和保存管理备注。摘要附记录编号，管理备注单独保存。制作 Agent 继续负责 PPT 和大阶段打卡，MCP 配置入口位于设置中的制作 Agent 接入。API 未启用或请求失败时，本地工作链继续记录。

## 分支与自动排布

项目内部默认展示详细运行路径。驻留助手按已保存频率读取调用增量，集中补图和整理记录，制作 Agent 无需逐工具报告 flow。制作 Agent 有明确的语义关系需要登记时，仍可随打卡提交 flow，既有图继续保留。详见[助手自动记录与补图](assistant-recording.md)与[工作图说明](project-work-graph.md)。
