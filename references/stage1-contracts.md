# 场景路径、提交预检与交付限制

## 场景路径

新编写的场景可以使用以下顶层字段。画布、页面和对象仍按原场景契约填写。

```json
{
  "version": "1.1",
  "path_base": "project_root"
}
```

1.1 场景的 `reference`、`asset` 和 `drawing` 都从项目根目录解析。场景移入 `plans` 或 `production` 后，素材路径含义不变。受管调用使用当前绑定项目，直接脚本可显式传入根目录，或使用 `PPT_USAGE_PROJECT`。缺少这些信息时，只接受唯一带 `workflow/state.json` 的祖先目录；找不到或遇到嵌套项目会报错。

1.0 继续使用场景文件所在目录，禁止添加 `path_base` 偷换旧文件的含义。构建版本与交付副本继续冻结为自包含的 1.0 场景，便于独立打开。

调用 `toolbox_project_inspect`，设置 `action="scene"`、项目和场景路径，即可查看 `path_preview`。每条记录包含字段位置、原值、实际解析路径和是否存在。项目内绝对路径只在导入副本中规范化，原文件保持原样。缺失、越界、目录歧义和不安全链接均需修正，不搜索同名文件代替，也不扩大项目授权。

## 提交预检

`toolbox_project_inspect` 的 `action="submission"` 返回当前任务的提交草稿。CLI 使用 `manager.py --data-dir <当前数据目录> prepare-submit --project <已授权项目>`。该入口只读状态，固定 `task_id`、`token` 和 `base_revision`，从当前任务生成待填结果。编辑和重建动作的 `kind` 取自当前要求，备注仍为空。批量审查的每项保持 `blocked`，不会声明看过文件或填入通过结论。

只编辑 `request.result`。CLI 通过 `--project` 指定项目时，从请求 JSON 中省略重复的 `project` 字段。任务身份变更后，先重新读取任务并检查工作是否仍适用，不把旧结果重新绑定到新 token。草稿的 `validation_status=not_run` 表示尚未预检。

`rebuild_validate_response` 使用当前任务的身份和 `result`，与正式提交共用字段契约和语义校验。返回所有当前可检查的问题，每项包含 `path`、`rule`、`object_id`、`next_action` 和修正说明。缺少前置条件的检查列入 `not_checked`。

普通字段错误按 `correct_result` 修正当前响应。申请生成素材与已选原生或保留路线冲突时，返回相关组件和 `revise`，先更新对应计划。预检不会填写文字转录、看图结论或通过状态。

`validation_binding` 记录任务、版本、任务包、状态及输入哈希。本批不复用预检缓存，正式提交仍检查当前状态与依赖文件。不能把一次预检结果当成可长期使用的提交许可。

CLI 预检入口为 `execute --tool workflow.validate_response -- --project <项目> --request-json <请求文件>`，提交入口为 `workflow.submit`。两步可以共用只含任务身份、版本和 `result` 的请求 JSON。

受管 CLI 在预检 `valid=false`、等待处理、参数错误、执行失败或结果未知时返回非零退出码；MCP 同步返回 `isError=true`。PowerShell 脚本应在每步后检查 `$LASTEXITCODE`，非零时立即停止依赖步骤。提交已接受但领取下一项失败时，同样停止脚本，保留接受回执，先查状态，不重放提交。非零退出码本身不会阻止使用分号串联的后续命令。

## 调用统计

`toolbox_project_inspect` 的 `action="calls"` 汇总当前项目的调用记录，按调用 ID 去重，分别列出工具、状态、失败代码、已知耗时和返回 JSON 的 UTF-8 字节数。

`result_json_utf8_bytes` 包含服务返回值中的 stdout、stderr，排除统计字段自身。单次记录的 `payload_json_utf8_bytes` 另行排除 stdout、stderr。MCP 外层传输、图像传输和模型输入 token 未测量，保留空值。日志文件字节单列，不能当成返回量。并行调用的耗时可能重叠，累计值不能代替任务总耗时。旧记录缺失的测量不补成零。

汇总最多读取 2000 个记录文件，并报告是否达到限制及不可读记录数。它描述调用记录，不能证明视觉质量或端到端制作速度已经改善。

## 编辑限制

`editable_behavior` 可在原有 `actions` 和 `files` 外提交 `edit_tests`。每项记录页面、对象、实际操作、`required` 或 `stress` 范围、结果、发现和证据文件，失败项还需给出 `required_adjustment`。`tested_value` 保存这次实际测试的值。证据文件必须同时列入 `files`。

必需操作失败时不能提交顶层 `passed`。现有长句越界回执仍会阻止通过，不能通过标记压力测试绕过。字符数只描述本次测试，不推算通用上限。

`toolbox_project_inspect` 的 `action="edits"` 查看当前记录，支持分页。新交付包会生成 `edit-summary.json`，并在 README 中直接列出编辑测试和调整要求。历史记录缺少逐对象数据时保留原动作和备注，覆盖范围标为 `legacy_actions_and_note`。已有交付包不重写。
