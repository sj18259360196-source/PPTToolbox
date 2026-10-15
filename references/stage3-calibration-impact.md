# 文字校准与修改影响分析

文字校准沿用 `ops.text-fit-plan`、`office.render` 和 `ops.text-fit-evaluate`。修改影响分析放在 `toolbox_project_inspect`，场景修改预览、`ops.patch-scene` 的报告和返修后的整页审查也会返回建议。现有视觉审查和复用条件保持原有含义。

## 代表文本校准

在已授权项目中调用现有执行入口，参数示例为

```text
ops.text-fit-plan --project PROJECT --mode calibration --scene plans/scene.json --outdir calibration/first
office.render --project PROJECT -Pptx calibration/first/specimens.pptx -OutputDir calibration/office -Width 960 -Height 540 -TextCalibration
ops.text-fit-evaluate --project PROJECT --plan calibration/first --office calibration/office --output calibration/measurements.json
```

`-Width` 和 `-Height` 必须使用计划返回的画布像素尺寸。Office 一次调用导出最多八个代表文本小样，每个小样独占一页，保留原坐标、文字、字号、段落和字体设置，避免未测量的文字溢出干扰另一项。生成计划和读取报告都不会启动 Office。

计划中的 `canvas` 保留源场景的逻辑坐标与物理尺寸。`export_size_px` 单独记录整数导出尺寸，每个维度取最近整数，恰好半像素时向上取整。例如逻辑画布 `1672×940.5` 仍保持原样，导出使用 `1672×941`。始终完整采用返回的 `office_arguments`，其中同时指定宽和高。校准小样继承最终场景的物理尺寸与字号，不要从另一套示例画布重建小样。

评价时核对冻结场景、PPTX 包内尺寸和实际 PNG。PPTX 尺寸必须与源场景按构建器换算出的 EMU 完全相同。Office 对页面尺寸的读回会舍入，本机 Office 16.0 的十个边界样本均符合最近 `1/8 pt` 格点；工具仅接受原尺寸的数值读回误差，或该最近格点的读回误差，数值容差均为 `0.001 pt`。真实页面缩放、非格点偏移和错误 PNG 尺寸仍会拒绝。报告的 `canvas_validation` 列出源尺寸、包内尺寸、Office 读回值、差值与匹配规则，便于判断原因。

旧整数画布计划缺少 `export_size_px` 时可按原整数尺寸校验。缺少该字段的小数画布计划需要重新生成。代码或字体、Office 环境发生变化时，旧测量仍按原有环境指纹规则重新测量，结构兼容不代表可以跨环境复用。

程序优先选标题、正文、数字、长句和中英文混排，再补首次出现的样式。一个样本可覆盖多个类别。24 字符以上或包含显式换行的文字进入长句候选，同类优先选最长文本。关键代表文字会单独测量，避免同样式的短标签掩盖长句溢出。其他普通文本的同类样式共享建议；它们的具体文字是否合适仍需检查。混合格式、旋转或效果文字单独测量，超出 `--max-samples 1..8` 的项目留在 `pending`，组内文字留在 `deferred`，不记为通过。

报告同时列出请求的字体名、Office 返回的字体名、显式行数与实际行数。名称不一致时提示复查，不能据此断言发生了字形替代，中文别名也可能造成差异。字形来源和绝对基线没有可靠读回时继续标为未确认。

测量报告包含文本边界、每行边界高度、相邻行的纵向间隔、Office 返回的运行字号及基线偏移。绝对基线坐标为 `null`，因为当前采集接口没有提供它。上下标偏移是相对普通基线的量，不能当成页面纵坐标。普通且关闭自动适应的文本可返回有效字号；混合格式、上下标或自动适应无法确认时，该字段留空，并注明原因。字体名称不构成每个字形实际来自该字体的证明。

工具会提示比较参考文字，发现文字越过文本框时建议检查框宽、边距和换行。Agent 根据参考图决定是否扩大文本框、调整布局或局部字号。工具不改场景，不统一缩字，不替 Agent 判断相似度。

后续页面可在同一入口追加 `--reuse calibration/measurements.json`。程序复核计划、冻结小样、Office 收据和图片哈希，再按当前样本重新读取测量。只有画布、文字、框尺寸与位置、格式和环境一致的高置信度普通样本能复用。字体文件、字体安装清单、Office 程序或采集代码改变，或者环境标识无法取得时，会重新测量。不同文字只共享样式建议，不复用文字适配结论。全部命中时计划返回 `reuse_only`，无需再次运行 Office。

## 修改范围建议

已有两轮冻结结果时，可直接读取

```json
{"project":"PROJECT","action":"impact"}
```

也可以通过 `toolbox_project_inspect` 比较显式场景

```json
{"project":"PROJECT","action":"impact","before_scene":"versions/before/scene.json","scene":"versions/after/scene.json"}
```

两个场景的路径分别按其版本规则解析。共享素材按文件内容比较，所有使用位置都进入建议；如果文件曾被原地覆盖且旧副本已经丢失，工具不能还原旧内容，需要提供 `changed_assets` 中的场景相对路径。缺失依赖会扩大范围。

建议包括变化字段、受影响对象、逻辑画布中的 `regions_xyxy`、越界提示和扩大范围的原因。移动覆盖旧位置与新位置，组合变化覆盖子对象，绘制顺序变化纳入遮挡检查。文字使用与两轮 PPTX 绑定的 Office 边界；缺少一轮测量、效果范围不明或邻近文字可能溢出时，扩大到整页。Office 版本变化或页面渲染变化无法由场景差异解释时，也安排整页复查建议。

整页审查任务只附带当前页的简短建议，最多列出二十项变化与对象。完整明细写在任务目录的 `revision-impact.json`，并纳入任务输入哈希。截断数量会明确标记，原有检查清单仍完整保留。

旧版证据不足时，任务注明影响分析不可用，继续要求当前页的正常审查。建议不会变成新的提交门槛。显式调用影响检查时，损坏的冻结文件仍会报错，便于定位证据问题。

`automatic_review_scheduling` 始终为 `false`。本批不新增自动跳过规则，不写通过记录，不减少原有必看图片和逐对象检查。后续自动安排任务需要继续用历史返修和真实修改验证，尤其要检查遮挡、越界、组合与共享依赖。
