# 批量描边与组件审查

`icons_trace_fragment` 保留原有单项调用。需要连续制作多个部件时，传入已授权的 `project` 和 `items`，每批 1 到 16 项。每项用稳定的 `id` 标识，`prefix` 用于生成对象编号。

```json
{
  "project": "C:/Work/PPTProjects/example",
  "items": [
    {"id": "shell", "mask_file": "assets/masks/shell.png", "semantic_name": "Outer shell", "box": [10, 20, 80, 60], "prefix": "shell"},
    {"id": "core", "mask_file": "assets/masks/core.png", "semantic_name": "Inner core", "box": [25, 30, 40, 35], "prefix": "core", "smoothing": "curves"}
  ]
}
```

`mask_file` 按项目根目录解析，也可改用原有的 `mask` Base64 字段，两者选一。蒙版仍须为 2 到 512 像素的不透明黑白图。批次沿用 Agent 执行开关、工具开关、项目授权和写入锁。单项纯计算调用保持原行为；MCP 的 `readOnlyHint` 为 false，因为该接口现在包含项目写入模式。

每项返回 `status`、`summary`、`result_file`、`result_sha256` 和 `reused`。完整原生路径保存在项目的 `assets/traces/<输入哈希>/result.json`，需要装配或检查时读取其中的 `scene_fragment`。批次不向返回文本展开全部路径，也不写全局素材库。

一个部件失败后，其他部件继续处理。根据 `retry_ids` 只重交失败项；重复提交成功项时，工具核对已有结果哈希并复用。已有成果损坏时保留文件并报错。相同输入的缓存键包括转换格式版本；修改描边算法或结果语义时须升级 `native-trace-item` 版本，不能沿用旧缓存。

整体参数、项目权限或锁不满足时，整次调用在描边前拒绝。单项参数、蒙版、计算超时或输出失败单独记录。受管 CLI 的批次请求上限为 16 MB；MCP 仍执行 1 MiB 传输上限，优先传 `mask_file`。每项沿用 30 秒计算上限，按项顺序执行。超时只终止该项纯计算子进程。全部项目失败时，批次状态为 `failed`，成功和失败并存时为 `partial`。

## 按组件审查

工具从 `element_scope.bindings` 和 `owner_id` 读取组件归属。导入的散落对象也可以在现有 `review_requirements` 中明确声明组件。

```json
{
  "review_requirements": {
    "components": [
      {"id": "chart-a", "object_ids": ["axis", "tick-0", "tick-2", "unit", "error-bar"]}
    ]
  }
}
```

组对象会展开到其子对象。显式组件不得重复占有对象，也不能引用未知编号。工具按这些归属生成涵盖全部成员的裁切框；没有归属依据的对象继续沿用原有区域，不按距离猜测组件。全页检查保留，裁切图不降低原有像素尺寸。

任务中的 `review_components`、`object_ids` 和 `object_check_ids` 列出当前组件及检查项目。Agent 查看任务要求的左右对比和叠加图，逐项填写 `object_checks` 的 `object_id`、`status`、`note`。关系对象仍分别填写 `relationships`；具体问题分别保存在 `findings`。工具检查记录覆盖与状态一致性，观察内容由 Agent 填写，模板保持 `blocked` 和空观察。

`review_full` 和 `review_local` 都可通过 `additional_reviews` 同时提交当前 `review_bundle` 列出的最多 6 个局部结果。局部任务加上自身，一次可提交 7 项。每项仍绑定自己的图片和对象，分别保存结果文件；省略的项目继续待检查。禁止嵌套批次、跨页代填和复用当前任务以外的区域编号。

同一提交内的格式、覆盖和文件绑定错误会阻止整次提交，可先调用 `rebuild_validate_response` 一次查看问题。合法的 `needs_changes` 结果会被记录并进入返修。已经发出的旧任务继续按原 packet 校验，历史审查复用仍核对场景、依赖和实际对照图。

## 统计口径

`project_inspect.calls` 将调用数与批内项目数分别统计。部分成功显示 `partial`，`item_counts` 记录成功、失败和复用数量，`item_failure_codes` 记录逐项原因。结果 JSON 字节数沿用第一批口径，不代表宿主网络流量或模型 token。
