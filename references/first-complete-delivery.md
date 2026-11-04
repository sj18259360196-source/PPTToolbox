# 首版优先提交 / First-complete delivery

## 中文说明

极速版的首版优先提交默认开启。开启后，软件立即提醒用户，本轮完成内容完整性核对后交付首版，Agent 不会继续自动调整排版或美化。

右侧的记住我的选择控制后续新项目。勾选时保存首版开关当前的开或关，之后多次新建继续使用该选择。切到标准版或精修版时隐藏首版选项，返回极速版后恢复记住的选择。不勾选时，首版开关仅影响当前新项目；取消记住后，后续新项目默认开启。保存结果以软件读回为准，保存失败时应明确提示。

记住的选择只影响未来项目。项目编号发放后，交付策略和合同保持冻结，后来的偏好变化不修改旧编号、旧制作记录或已交付文件。

开启后的流程保留登记、拆分、位置标注、原文核对与原生对象制作。全部页面完成后，实际查看本候选的 Office 左右图，逐单元核对文字、数字、图片和其他元素齐全可见。多页项目必须整套完成，首版按实际 PPT 文件、页数和哈希绑定，不能按 run 目录编号认定。

首轮只补具体缺项。位置精度、字形相似度、颜色和装饰差异留待用户反馈，默认不生成叠图或局部外观任务。文件损坏、漏页、原文缺失、错误素材和预览来源不一致仍阻断交付。原生制作继续按当前合同执行，整页截图不能代替文字和对象；用户明确要求的专项编辑或复建验证继续保留。

核对通过后发送同一份 PPT，结束本轮并等待用户反馈。重复完成、重启或重新连接返回已有首版，不自行开始下一版。用户明确提出修改后，进入新的反馈轮次，按指定改动及适用任务核对，保留原首版和原冻结合同。

## English guide

First-complete delivery is an optional setting in the Fast tier and is on by default. An explicitly remembered off choice takes precedence. Enabling it immediately tells the user that this turn will end after the first complete deck is delivered. The Agent will wait for feedback before further layout or decorative refinement.

Remember my choice saves either the enabled or disabled choice for future projects. With this option selected, the choice survives repeated project creation and is restored when the user returns to Fast after selecting Standard or Refined. Without it, the delivery choice applies only to the current new project. Clearing Remember my choice removes the saved preference, and subsequent new projects default to first-complete delivery. The UI must confirm the server's saved state and report a failed save.

The preference affects future projects only. Once a project number is issued, its delivery policy and acceptance contract are frozen. A later preference change cannot alter an issued project, its earlier production records, or an existing delivery.

The initial workflow retains registration, source decomposition, position annotation, exact source text checks, and native object construction. After every page has been built, the Agent views the current PowerPoint side-by-side comparisons and checks each annotated unit for complete and visible content. The first delivery identifies the actual complete PPTX by its file, page count, and SHA-256. A run directory name does not identify the first complete deck.

Only specific missing or invisible content is repaired in the initial phase. Layout precision, font similarity, color differences, and decoration wait for user feedback. Overlay images and local appearance review are not scheduled by default. Invalid packages, missing pages or text, wrong assets, and stale preview provenance still block delivery. Existing native construction requirements remain, and a flattened full-page screenshot cannot replace the text and objects. Explicit user requests for editing or reconstruction verification remain applicable.

After completeness checks pass, the Agent sends the reviewed PPTX and ends the turn. Repeated finish calls, restarts, and reconnections return the same first delivery. A new revision begins when the user explicitly provides feedback. The original first delivery and frozen contract remain preserved while the requested changes receive their applicable checks.

## Developer contract

The project uses the immutable `delivery_policy` object with version `ppt-delivery-policy/1` and mode `normal_review` or `first_complete`. The initial first-complete project uses acceptance contract `ppt-acceptance-trial/0.7`. Missing policy metadata means the historical workflow and must not be backfilled on read. The project, page, and region settings must all use Fast for first-complete delivery.

Remember my choice is a separate owner preference under `production_ui:first_delivery`. It is returned as `delivery_preference` and saved through the owner action `production.delivery-preference.save` with a revision check. It does not enter the project's delivery-policy hash. Agent-facing MCP and CLI reads use the issued project policy, not the owner's latest UI preference.

The controller, task schema, submission preflight, final evidence gate, prompts, project state, and management assistant read the same frozen project scope. Checks outside the initial scope are recorded as not required. They must not be reported as performed or passed.
