# 项目运行路径

运行路径附带图片使用统计及整页主视觉、高清局部节点。数字来自任务要求和 Agent 观察回执，不能当成实际上传量或视觉通过。图片缺失和证据异常在项目顶部及统计面板同时显示，统计暂不可用时显示未知。手工登记的步骤状态保持独立，图片统计不推进大阶段。详细口径见 [多页制作与修订](multipage-efficiency.md)。

软件在项目内用流程图显示步骤、分支和汇合，从左到右排列，满行后接下一行。折线绕开方框，连线显示关系类型，选择节点后可查看条件、依据、结果和下一步。没有细分计划时，软件按任务编号归类调用，并给出通往合成、预览、核对、编辑验证和交付的建议路径。虚线为建议，点线为阶段归属。历史调用本身不能证明依赖关系，软件不会把建议连接当成执行事实。已结束的项目不再补待执行的建议节点。

默认图展开最近 16 组任务、6 条重新规划或恢复记录、4 条素材路线，完整历史留在调用与阶段记录中。同类步骤在不同任务中分开显示，避免旧错误覆盖新任务。图片计数只表示任务要求和观察回执。自定义图的末端没有后续、又没有结束结果时会提示补充关系，不阻断制作。

软件负责方框位置、箭头和状态样式，Agent 不提供坐标、颜色、SVG 或截图。工作图不会推进制作阶段，也不会自动批准交付。

## 制作 Agent 更新

大阶段仍按原规则打卡。需要细分路径时，在同一次 toolbox_checkpoint 或 rebuild_next / rebuild_submit 的 checkpoint 中加入可选 flow 数组。首次提供步骤与前后关系，之后只提交编号和变化字段。普通工具调用无需增加汇报。

下面是 flow 字段的示例。具体步骤与状态必须来自本项目的计划或执行记录。

```json
[
  {"id":"analysis","title":"参考图分析","status":"done"},
  {"id":"plan","title":"制作计划","status":"done","after":["analysis"]},
  {"id":"text","title":"文字与排版","status":"done","after":["plan"]},
  {"id":"search","title":"图标素材搜索","status":"skipped","after":["plan"],"detail":"未找到合适素材"},
  {"id":"draw","title":"调整为原生绘制","status":"running","after":["search"]},
  {"id":"compose","title":"整页合成","after":["text","draw"]},
  {"id":"review","title":"画面检查与编辑验证","after":["compose"]},
  {"id":"deliver","title":"交付","after":["review"]}
]
```

步骤改变后，只需提交对应项。

```json
[
  {"id":"draw","status":"done"},
  {"id":"compose","status":"running"}
]
```

| 字段 | 用法 |
| --- | --- |
| id | 稳定编号，后续更新沿用 |
| kind | 常用步骤类型，软件据此关联工具、名称和入口 |
| title | 指定 kind 时可省略；自定义步骤需要填写，最多 80 字 |
| after | 前置步骤编号，多个编号表示汇合，省略时新步骤没有前置项 |
| status | planned、running、done、blocked、paused、skipped、replaced、failed、outcome_unknown，新增项默认 planned |
| detail | 可选说明，最多 1500 字 |
| stage | 可选关联大阶段 |
| tools | 可选关联工具 ID，软件据实际调用显示执行中或异常，单次调用成功不会自动完成整个步骤 |
| task_ids | 绑定具体任务编号，隔离不同轮次的调用和错误，最多 12 项 |
| evidence_ids | 可选依据编号，最多 12 项 |
| links | 对 after 中的每个来源补充 from、relation、label、basis、evidence_ids，同一个来源只出现一次 |
| result / next_action | 结果和下一步，各最多 600 字 |
| round | 修订轮次，1 到 999 |

relation 支持 dependency 依赖、sequence 先后、decision 决策、merge 汇合、revision 返修、suggested 建议、grouping 阶段归属。basis 支持 recorded 记录依据、agent 制作 Agent 登记、inferred 推断、suggested 建议。调用先后只能证明顺序，不能单独证明依赖。label 用于说明条件或去向，最多 120 字。未填写 links 的旧 after 继续按 Agent 登记的依赖显示。

优先使用 33 种预设类型。预设不适用时，每批补一到两个自定义节点即可，无需凑齐全部节点。新增自定义节点省略 kind，填写 title。分支接回合成或核对；返修新增节点和 round，之后连接复查与交付，不覆盖上一轮的失败。相同任务重试沿用编号，不重复登记路径。

```json
[
  {"id":"feedback-2","kind":"feedback","after":["review"],"round":2,"result":"用户要求调整标题"},
  {"id":"repair-2","kind":"repair","after":["feedback-2"],"round":2,"task_ids":["task-000021"],"links":[{"from":"feedback-2","relation":"revision","basis":"agent","label":"只修改标题","evidence_ids":["feedback-checkpoint-2"]}]},
  {"id":"recheck-2","kind":"recheck","after":["repair-2"],"round":2,"next_action":"通过后整理交付文件"}
]
```

每图最多 64 个步骤。软件检查重复编号、缺失前置步骤与循环。返工应新增步骤并连接到后续环节；旧路径保留，取消或替换的步骤标为 skipped 或 replaced。

## 驻留 PPTAgent 更新

PPTAgent 可在用户选定的项目内调用 read_project，取得 sequence 与已有 work_graph，再调用 update_work_graph。patch_json 是上述步骤数组的 JSON 字符串，支持相同的增量更新。

read_project 同时返回步骤字段合同、近期阶段说明和缺少后续关系的节点。驻留助手根据已接入的工具结果、阶段说明与明确反馈整理关系，不能读取外部制作 Agent 的全部对话。默认图由本地规则生成，不请求模型。需要助手整理自定义图时仍沿用现有管理任务入口和 API 配额；不为每次工具调用另起请求。制作 Agent 在已有打卡中批量附带 flow 即可，正常工具调用无需增加汇报。

并发更新时，旧 sequence 会被拒绝。重新读取后，只提交仍需要修改的字段。驻留助手只整理展示信息，不能代替制作 Agent 打卡、修改 PPT 或宣称用户已验收。

## 状态来源

阶段记录、制作 Agent 登记、PPTAgent 整理与实际工具执行分别标明。工具失败显示执行失败，结果无法确认时显示结果待确认；授权、输入、Office 占用和素材待检索等情况显示等待处理，并说明原因。没有可关联的执行证据时，图保留登记状态；不会从连接在线推断项目正在运行。

自动采集的细分节点在工具成功返回后显示灰蓝色的调用已完成，无需另行打卡。这个显示状态只说明关联调用已完成，制作阶段和 Agent 登记步骤的完成状态仍由原有记录决定。存在未处理异常时，节点继续显示具体异常。

## 常用步骤与入口

| kind | 显示名称 | 可用入口 |
| --- | --- | --- |
| intake | 任务接入 | 项目说明、调用记录 |
| analysis | 参考图分析 | 项目文件、调用记录 |
| plan | 制作方案 | 项目说明、调用记录 |
| text | 文字与排版 | 当前 PPT、调用记录 |
| search | 素材检索 | 素材库、调用记录 |
| material | 素材制作 | 图形构造、素材库、调用记录 |
| fidelity | 相似度判断 | 项目文件、当前 PPT、调用记录 |
| generation | AI 生图 | 项目文件、调用记录 |
| crop | 素材裁剪 | 项目文件、调用记录 |
| compose | 整页合成 | 当前 PPT、项目文件、调用记录 |
| preview | 导出与预览 | 当前 PPT、调用记录 |
| review | 核对与修订 | 当前 PPT、调用记录 |
| delivery | 交付整理 | 项目文件、调用记录 |

补充预设包括 requirements 需求与修改范围、resume 恢复上下文、region_plan 页面分区、source_text 原文与数字核对、route_decision 制作路线决策、native_draw 原生图形绘制、asset_place 素材回装、text_fit 文字适配、visual_review 整页视觉核对、detail_review 局部细节核对、edit_verify 编辑与读回验证、feedback 用户反馈、revision_plan 修改范围判断、repair 局部返修、recheck 返修复查、recovery 异常诊断与恢复、reproducibility 重建与复现验证、acceptance 等待用户确认。

例如新增素材制作分支只需 `{"id":"draw","kind":"material","after":["search"]}`。只有状态变化时继续提交 id 和 status。阶段打卡次数保持原样。

没有自定义工作图时，带 generation_decision 的生图请求会自动增加绘制、相似度判断、AI 生图与放入 PPT 分支。multi_icon_sheet=true 时增加多图标裁剪节点。用户要求直接生图时省略绘制节点，路线判断显示用户指定。阈值为严格低于 75%，节点注明分数来自 Agent；低于阈值本身不会显示报错或等待处理。

生图素材经实际文件校验并提交后显示素材已登记。同图素材在场景中出现多个 source_crop 图片对象后显示裁剪已登记；单独裁出新文件时，可在自定义工作图中登记裁剪结果。自定义工作图继续由 Agent 使用上表的步骤类型维护，软件不擅自改变其连线。宿主生图工具未接入工具箱调用记录时，节点保持待执行，直到产物登记；不会凭任务已分配就显示调用中。

参考图分析、方案和排版由制作 Agent 使用工具完成，方框提供相关文件与调用入口。素材检索和图形构造有对应操作页。核对与修订可显示 Agent 与工具的记录，项目页继续使用简单 PPT 预览。

## 异常处理

项目顶部持续显示未处理异常，相关步骤也会标出失败或等待原因。单次调用成功不代表整个步骤完成。无关调用成功不会清除之前的异常；同一任务、同一工具的成功重试才可自动解除普通错误。

执行超时或工作进程退出且缺少结果时，保留结果待确认。已经接受提交但获取下一步失败时，明确提示提交已保存，避免重复提交。软件不会自动重放写入、解除写入锁或扩大权限。

用户可在核对后收起提示。操作保留异常原文和记录，只影响提示显示，不会将工具结果改为成功。采集失败时显示最近可用记录的时间；API 助手不可用时，本地采集继续运行。

图标和图形工具通过当前绑定项目或显式目标目录归属记录。从项目内打开素材页会携带项目上下文。没有项目上下文的调用保持独立，不分配给任意项目。外部脚本或其他软件里未接入工具箱的活动仍需 Agent 在大阶段打卡时说明。
