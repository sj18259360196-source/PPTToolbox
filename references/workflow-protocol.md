# 控制器与续作协议

## 作用范围

本阶段把原来由Agent手工编排的步骤集中到toolbox.py。它没有内置大模型、OCR或后台进程；不会自动发现原图中的所有对象，也没有通用scene→COM编译器。高级视觉组件仍使用现有原生模块/手册，新的参数化组件属于后续阶段。

## 状态与退出码

command_status说明本次命令是否执行成功；workflow_status说明制作进度。需要Agent或宿主继续时退出0，错误提交/坏文件退出2，确定性工具执行失败退出1。

| workflow_status | 下一步 |
|---|---|
| awaiting_analysis | 读当前page_plan或region_objects任务 |
| awaiting_source_review | 对原图核对转录、数字、关系、遗漏 |
| awaiting_asset_generation | 调用真实宿主生图/素材能力并提交文件 |
| awaiting_candidate | 使用冻结scene构建外部候选，再提交真实PPTX |
| awaiting_office | 真实Office导出后提交收据；缺能力时可显式preview进行独立预审 |
| awaiting_preview_review | 打开LibreOffice全页与局部对照；不会填入正式Office记录 |
| awaiting_visual_review | 打开返回的全页/局部对照，记录具体差异 |
| awaiting_edit_check | 在副本上完成编辑或重建测试 |
| awaiting_revision | 有问题需要修改，或review-again补审；不从头运行 |
| tool_failed | 查failure字段，解决环境/参数后显式retry |
| interrupted_operation | 上一程序步骤未提交结束状态，检查产物和Office后retry |
| ready_to_deliver | finish重新检查当前证据并发布 |
| delivered | 已发布，保留现有版本 |

next会自动完成已就绪的freeze、build/import、inspect和compare；配置了--office并实际在Windows时才调用PowerPoint。可单独用advance推进程序步骤。已有活跃任务时advance不会越过它。没有自主后台工作。

## 一次只保留一个活跃任务

每个项目用一个原子状态文件存当前任务与事件记录；writer.lock阻止并发写。任务绑定项目ID、版本、输入文件哈希和一次性token。重复next得到同一任务。submit格式错误不提交状态，旧版本提交被拒绝。

单写任务粒度是为减少模型和进程之间的覆盖。本阶段不支持多个Agent并行修改同一项目。不同项目可独立执行，Office进程仍需尊重用户文档。

如果进程中断，锁可能留下。不要自动删除或杀Office。检查writer.lock的主机、PID和token，确认不存在写者后执行unlock --confirmed-no-active-writer --token <token>。这项确认来自调用者，程序不会冒充跨机进程探测。

## 持久化布局

```text
project/
  input/                       原始参考副本与引用清单
  assets/                      内容寻址的独立素材
  workflow/state.json          权威状态与事件记录
  workflow/tasks/task-000001/   packet、局部参考和响应模板
  workflow/results/            不可覆盖的已接受任务
  runs/run-0001/               冻结scene、素材、候选、Office、对照及审查
  delivery/run-0001/           最终发布的PPTX和production证据
  HANDOFF.md                   可重新生成的交接摘要
```

每次运行冻结输入，不直接引用剪贴板或系统临时原图。状态内保存相对路径，next按当前根目录返回可打开的绝对路径。原图、素材、冻结scene和已经提交的记录发生外部改写会拒绝继续；恢复原文件或明确新建修订，不能改哈希字段。

## 分区和坐标

page_plan使用原图像素xyxy。region_objects使用该裁图内部的像素xywh、端点和路径坐标；字体与线宽使用pt。程序负责增加裁图偏移并转换到逻辑画布。每页保留自己的映射；默认只接受比例一致或约1像素取整差异。明显比例差异需明确选择explicit_stretch或导入已审查的映射，不能偷偷拉伸。

最终比较仍使用每页原图像素尺寸；像素分数只供同一原稿的版本比较。自动ROI按声明对象/来源分区生成，不能发现完全漏建的原图元素，source_review仍必须独立核对。

## 已有PPTX

start --scene <scene> --candidate <pptx>保留原文件，只复制到新项目。默认切换external构建模式。start --builder external也可让模型在冻结scene后使用COM/其他后端构建，再交回候选。

程序验证候选对象ID、类型、文字与scene，并接入既有第一阶段渲染/对照/审查。不运行Python重新覆盖外部文件。当前通用scene仍受原schema范围限制，SVG/图片填充等复杂格式若未被表达，需明确适配，不删除要求来过校验。

## 修订与补审

revise --slide ID --region ID只重开指定区域，已提交兄弟区域保留；不传region则重开该页分区。旧run完整保留，新的PPTX需要重新绑定视觉证据。暂未实现只重渲染受影响单页或区域外像素回归，这些属于后续性能/返修能力。

replace-scene用于已有完整scene的明确修改，要求页ID、页数及参考图身份不变，原图来源检查重做。replace-candidate用于相同scene下的外部文件更新，生成新run，不复用旧视觉通过。

replace-scene 会在原始分区记录、参考图、画布和映射仍可核对时保留审查分区。对象位置或尺寸调整后，局部对照范围包含其当前几何；同一分区前缀下的新增对象一起检查，无法归属的必查对象另建局部对照。分区保留只组织审查，不恢复修改权限、旧 token 或通过结论。关键分区和全部必查对象仍须覆盖，整页看图也照常保留。

review-again --task <已接受审查ID>用于补充或纠正同一候选的审查断言，保留旧记录，重开对应检查，不重建文件。它不等价于用户认可。

retry只重试失败或中断的程序步骤。已完成的候选、导出和对照不因重试被无条件覆盖。程序发布目录采用新名称/暂存后原子发布；无效提交产生的调试文件不作为有效证据。

## 信任与真实执行

控制器能检查文件、来源、对象声明、任务覆盖和状态，不证明Agent诚实或看懂图片，也不能阻止宿主完全绕过工具箱。自动生成的状态不应被解释为跨模型质量认证。修改副本和日志需要真正执行；手填动作记录仍属于Agent声明。

新版预审状态和素材决策提交细节见[实测衔接修复](preview-and-handoffs.md)。
# Evidence-Bound Recovery Note

STAB W1, 2026-09-27, closes the original imported-scene recovery failure.
An imported slide without a plan must not be edited with a fabricated empty
plan. Regional revise may restore only original accepted planning authority
whose packet/reference hashes, canvas, geometry, object provenance and mapping
still match the frozen evidence. It issues new tasks and invalidates reviews;
it never restores a historical token or passed gate.

If geometry/reference/mapping changed or the basis is missing, use the original
full-page revise/replanning route. Workbench labels unplanned, invalid,
awaiting_replanning or recovery_blocked independently of active_task=null.
Read-only page load and polling do not call next to repair a task.

The actual W1 browser held draft29 at native21, while MCP adopted native23.
The original standard write endpoint rejected the stale baseline and kept23.
This is separate from the prior metadata-only conflict. Evidence is
`checks/native-capabilities-20260927/stability-r03`; current paired files and
outside objects were rechecked after rejection. Do not infer content safety
solely from a revision increment.
