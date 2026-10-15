# 可靠性与恢复

恢复从当前状态、调用标识和持久收据开始。保留旧任务、失败文件和原始证据，不按旧聊天猜测结果，也不自动重放已接受的写入。

## 依赖副本

场景替换、试验副本与正式冻结使用同一场景依赖收集规则。`scene-dependencies/1` 清单保留文件、用途、引用位置和 SHA-256，覆盖参考图、素材、生成依据、来源绑定及需求文本。场景替换先把归一化后的完整依赖转入项目，再清理导入临时目录。副本在 Office 启动前检查缺文件、哈希和路径边界。

复制前检查完整目标清单。已存在且哈希相同的文件可以复用；同路径内容不同时拒绝操作并保留原文件。复制后再次核对哈希。

遇到缺依赖错误时，先检查场景字段与副本清单，从合法来源补齐，再在副本目录独立校验。后续无法运行的语义检查记为未检查，不把需求文件缺失引出的连锁信息当成多项独立失败。场景 1.0 与 1.1 的既有路径语义继续生效。

## 图形预览

预览在受控工作进程执行依赖导入、编译和 PNG 转换。保留 `preview_call.call_id`，用 `graphics_preview_status` 取回同一调用；需要取消时用 `graphics_preview_cancel`。终态、超时参数和图片返回位置见[图形构造](graphics-construction.md)。

连接中断后先查询持久状态和已经发布的图片。完成结果直接取回，`outcome_unknown` 先查身份和收据。当前机制验证与原预览卡点的定位分别记录，不能把受控阻塞测试当成已定位历史挂起。

`preview_call.timing` 记录进程启动到工作入口、各模块导入、图形编译、PNG 转换、结果发布和当前响应组装的耗时，单位为毫秒。工作阶段使用单调时钟。超时或中断时保留已完成阶段，未完成阶段的结束时刻会注明来自管理进程观察。`transport_to_client_ms` 保持空值，工具端无法测得宿主接收和显示耗时。旧调用没有这些记录时，不能追补推算。

进度文件暂时无法读取时保留最后确认的步骤，截止监督继续执行。必要收据或图片持续无法读取时，返回 `retrieval_status=unavailable` 和原 `call_id`。若已确认执行完成，`execution_status=completed` 继续保留；恢复访问后查询原调用取回图片，不重新预览。

## 编辑证据替代

重复执行同一组编辑检查可使用[编辑验证程序](edit-runner.md)。它生成绑定候选的操作计划，并保留各次测试自己的收据。复用只适用于同一候选、同一操作和相同环境下已核验成功的检查，不代替下述失败证据的正式替代流程。

任务接受的附件可以位于当前项目的 `evidence` 目录。最终验收先核对接受时的 SHA-256，再把当前 run 以外的附件按内容哈希归档到 `review-evidence/attachments`，使最终验收和交付副本都能解析同一份证据。原始附件与候选 PPT 保持原样；跨项目文件、哈希改变或归档冲突继续拒绝。

通过 `review-again` 重开审查后，旧 gate 失效，旧 gate 失败保留在 `review_reopened` 历史详情中。当前任务继续等待新审查和 gate，不再显示那次已经失效的 gate 错误。其他阶段的失败与未决操作继续保留。

编辑验收结果可提供 `evidence_index`，其结构为 `{file, sha256}`，文件必须在当前项目内且哈希匹配。索引使用 `edit-evidence-index/1`，绑定项目、run、候选 SHA-256 和每项具体检查。

```json
{
  "format": "edit-evidence-index/1",
  "project_id": "current-project-id",
  "run_id": "current-run-id",
  "candidate_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "entries": [
    {
      "id": "long-text-001",
      "test_case_id": "title-long-text",
      "slide": 1,
      "object_id": "title",
      "action": "text.set",
      "check": "longer_text_layout",
      "receipt": {
        "file": "evidence/edit-001/edit-readback.json",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      },
      "input": {
        "file": "runs/run-0001/candidate.pptx",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      },
      "output": {
        "file": "evidence/edit-001/edited-copy.pptx",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      },
      "supersedes": [],
      "reason": "同一长句的保存重开检查"
    }
  ]
}
```

示例中的 ID、路径和零哈希均需替换为当前记录。索引不提供通过结论，结论来自真实 `ppt-edit-readback/1` 收据及其输入、输出和渲染哈希。每个检查必须包含 1-based `slide`，按 `test_case_id`、`slide`、`object_id`、`action`、`check` 匹配同一问题。

首个检查的输入必须匹配候选哈希。派生检查通过 `derived_from` 指向前项，且前项输出哈希必须等于本项输入哈希，并保持同页同对象。`supersedes` 指向被替代的具体检查 ID，保留历史文件并填写理由；不同候选、案例、页面、对象、动作或检查项不能相互替代。循环、断链、改文件或未解决失败均拒绝。

替代同一长文本试验时，文字和操作内容必须保持一致。只允许调整 `font_size_pt`，且新收据须有 `font_size_matches=true`。缩短句子不能解决原长句案例。`longer_text_layout` 只有真实 `within_frame` 才可通过，旋转或边界不可读的 `not_assessed` 仍需验证。具体字号字段见[编辑读回](codex-assistance.md)。

## 提交与打卡

`submission` 与 `checkpoint_receipt` 独立报告接受、派发、任务或打卡 ID 以及两套版本。打卡保存后任务拒绝，只修当前任务结果；任务已接受，后处理失败也不重交。重复打卡保留原 ID 和原内容，同 ID 不同内容及版本冲突继续拒绝。字段与重试范围见[项目工作链](project-work-chain.md)。

异常和超时仍需保留已知结果。未知部分明确为 `unknown`，先检查收据和当前状态。不能用整次调用的错误状态推断所有动作都没有生效。

## 精简返回与完整结果

`response_detail=compact` 保留当前任务、约束、有效设置、错误、未知结果和独立接受事实。完整事实在投影前保存，`detail_reference` 包含格式、哈希和查询入口。保留 `full` 模式，旧调用可能没有完整结果档案。

```json
{
  "project": "当前已授权项目",
  "action": "response",
  "call_id": "0123456789abcdef0123456789abcdef"
}
```

把上述参数传给 `toolbox_project_inspect`。`call_id` 为该调用返回的 32 位小写十六进制标识。查询返回 `available`，成功时完整事实位于 `result`。项目身份、调用身份、格式和 SHA-256 必须匹配；旧收据或缺失档案会明确返回不可用，不能自动补写或重交。

完整结果档案的保存和查询上限为 `32 * 1024 * 1024` 字节，即 32 MiB。超出时精简投影退回 `full` 并给出 `compact_fallback`，不截断 JSON。`detail_reference.query` 为实际可调用入口，历史查询结果不自动授权再次提交。`delivery_metrics.total_json_utf8_bytes` 给出包含计量字段的实际字节数。无活动任务的普通 finish 目标为 10,240 字节；必要的错误和未决限制继续内联，超出目标时保留完整有效 JSON。

## 运行环境与验收

`toolbox_project_inspect action=calls` 同时返回 workflow_timing。总时长从工作流创建到交付或查询时刻计算，包含模型工作、工具运行、停顿和用户等待；它与可能重叠的工具调用累计耗时分开。operation_windows 和 rework_counts 仅来自已保存事件，缺失的历史阶段不补造。

使用统计按 graphics 调用标识去重。开始事件和预览轮询不计调用结果，成功、失败、超时、取消、中断及结果未知分别保存。升级后首次查询会重建原 graphics 统计投影，原始审计日志保留。

先核对当前安装入口的工具列表、describe 和 instance。源码能力、受控子进程测试、真实 Office 保存重开和 GUI 操作分别记录。历史挂起缺少请求时保留该缺口，不能从新的阻塞测试推定历史原因。
