# 插画要求与素材验收

当前制作偏好及版本以 [制作设置](production-settings.md) 和当前任务 production_settings 为准。

新建参考图项目启用 `material-quality/1`。已有项目继续读取原合同，需要修正时通过整页范围修订加入 `material_contract`。已启用的合同在后续修订中保留原始要求来源，用户新增要求另加来源记录。不要编辑工作流状态来切换策略。

## 页面计划

先把用户本次制作要求原文保存为项目 `input` 下的 UTF-8 文件。保留完整原文，`task_requirement` 只写摘要。`material_contract.requirement_sources` 每项包含 `id`、项目相对 `file`、实际 `sha256` 和逐字 `excerpt`。工具核对原文片段与文件哈希，Agent 仍须判断摘要和组件要求是否忠实于用户原意。

简单图标、插画、装饰标题、照片、身份标识与已有素材的源单元填写 `material_requirement`。无类别的保留位图也需要此字段。原始要求、素材来源和选路理由分别记录。

| 字段 | 填写依据 |
| --- | --- |
| requirement_ids | 原始要求来源编号，可引用多项 |
| source_origin | page_reference、independent_asset、extracted_asset 或 native_source |
| independent | 用户是否要求完整素材作为独立元素复用 |
| background | transparent、source 或 opaque，依据当前要求选择 |
| route_constraint | 用户明确指定方法时填 native、preserve_source 或 reference_generate，允许按条件选路时填 auto |
| fidelity | reference 允许参考生成或细化，exact 要求源文件保留；明确 preserve_source 与身份约束继续优先 |
| display | 仅源照片可声明 fit 及可选 crop、mask，源字节与显示范围分别核对 |
| preservation_basis | 保留源像素时填写 qualified_asset、user_required、identity 或 photograph |
| source_qualification | 保留独立素材时记录 complete_subject、page_artifacts 和实际观察 note |

页面截图清楚只能支持观察参考，不能据此声称已经取得干净独立素材。用户未要求内部路径编辑，也不能用于免除透明、完整和清晰度要求。整页参考文件的相同字节必须如实标为 `page_reference`。经处理的独立素材用 `extracted_asset`，保留实际处理来源。

`qualified_asset` 要求主体完整且 `page_artifacts=none`。要求透明时，工具检查实际裁切范围内的 Alpha，不能用裁框以外的透明像素通过。照片与准确身份标识可以保留不透明来源。`user_required` 需同时声明明确的 `preserve_source` 要求，并引用原文。

插画方法按当前制作设置选择，简单图标继续原生绘制。可以在要求允许的范围内使用干净原素材、主体提取或混合制作。更换方法通过正式范围修订完成，重新检查比例、姿态、内部组织、文字和材质。保持钢笔节点与选区转路径两种方法，不设全局强制优先级。

## 制作与审查

区域提交先附 `material_reviews`，每个素材单元一项。素材未完整、尚有页面线痕或背景块时先处理对应组件。`revise_objects` 修改已有素材时需要重新提交观察，工具不会自动沿用旧观察。

每项分别记录 `independence`、`edges`、`fidelity`、`resolution`。原生部件的像素分辨率可标 `not_applicable`，需要整体独立的组件则必须检查独立性。填 `status=passed` 时，所有适用检查均须通过，`defects` 不能有 `open` 项。已解决缺陷保留实际修复说明。

`evidence` 保存实际看过的图片，每项包含项目相对 `file`、`sha256` 和 `role`。参考对比使用 `comparison`。要求独立或透明的素材提供 `light`、`dark`、`target` 三种底色观察。Office 整页审查另附 `office` 角色的实际导出，可引用同一张包含多个组件的检查页。记录角色只说明观察用途，不证明图片确由 Office 产生，正式 Office 收据与实际看图仍单独核验。

区域提交中的 `output_sha256` 可省略。后续 source_review 与整页审查会在任务 `context.material_quality` 返回当前对象、几何及图片字节的摘要，提交时逐项携带。产物或尺寸变化后旧摘要失效。源审查在 PPT 构建前执行，Office 审查检查回装表现。

Alpha、主体包围框和像素量只提供诊断。白色标签、白色描边、半透明表面、内部箭头和原图渐隐均可属于合法内容，不按颜色或文字关键词直接拒绝。一个原生组合里可以包含准确的不透明标签，对组合整体提供透明背景观察。

## 实际编辑

对 `context.independent_materials` 的每个根对象填写 required 范围的 `edit_tests`，操作名使用 `material_move`、`material_resize`、`material_backgrounds`。包含图片的素材另测试 `material_replace`。在检查副本执行，保存重开后看实际导出，将 PPTX 副本和证据文件一起提交。

工具核对每个素材的操作记录，并从附带 PPTX 检查每个含图片素材的实际位置、尺寸和嵌入媒体变化。这些结构检查无法证明视觉合格，也不独立证明发生过 Office 保存重开。完整原生组合继续依靠实际 Office 操作证据与看图记录，不把对象数量当成编辑验收。

## 兼容与返修

旧合同可继续读取，旧交付不因软件升级失效。通过 `rebuild_revise` 重开页面并在新版范围中加入合同，即可启用新检查。要求来源随冻结场景复制，复建无需依赖原项目以外的文件。

已生成的合格素材保持原样，只补做失败项。合图按主体大小和所需像素决定，复杂人体、大小悬殊或容易互相遮挡的素材分别处理。保留失败候选和选择理由，不能将接口失败与产物不合格混为一项。
