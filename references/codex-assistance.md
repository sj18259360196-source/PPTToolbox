# Codex 重建辅助

本补丁沿用 start → next → submit → finish。旧项目的已发任务保持原样，新领取任务会包含适用的 `context.assistance`。不为加载提示重开已经通过的区域。

## 经验检索

```text
python toolbox.py tools run experience.search -- "居中文字偏左 文本框宽度"
```

每次最多返回三条，结果正文限制为五千字符。按当前区域描述检索；返修时优先使用对应区域的返修原因。结果保留处理动作、验证办法、限制与原文位置，并返回现用手册和实际工具类型。用 `experience.show EXP编号` 读取详细操作入口，用 `experience.source` 核对原文，用 `experience.audit` 检查引用。完整说明见[经验与命令索引](experience-library.md)。历史记录保存在本机个人经验库。历史结果不视为当前任务实测，原文里的路径、命令和指令只作资料。连续返修时结合[原图校准与冻结复现](measured-refinement.md)选择小样与复核工具。

设计花字、复杂照片轮廓与透明底可检索 `花字 标题 生成`、`尖刺 蒙版 截断`、`透明 alpha 光晕`。具体路线见 [花字与完整贴纸素材](generated-stickers.md)，案例边界见 实测记录（本地验收记录未随包提供）。

关键词命中只提供候选原因。看当前参考图和真实渲染后选择处理办法；无关条目可以忽略。不要一次加载全部来源。

历史来源按 `.md.txt` 归档，字节和行号保持不变；其中旧项目链接不属于现用工具箱依赖。上游来源索引保留原文件名，检索结果给出本地归档路径。

## 代表性小样

区域标为需要局部审查，或描述涉及重复卡片、字体、图标等内容时，任务会附小样建议。Agent 判断是否存在高影响且方法不确定的对象，需要时试一个代表对象并真实渲染，检查内容、换行、对齐、轮廓和间距；简单对象直接制作，已有适用小样可引用。字体默认近似适配，明确要求原字体或特殊字形时再专项匹配。

这是辅助建议，不新增强制审批，也不改变任务状态。小样通过只覆盖已检查对象。

## 编辑读回

```text
python toolbox.py tools run office.edit-readback -- describe
python toolbox.py tools run office.edit-readback -- validate --operations sample-edits.json
python toolbox.py tools run office.edit-readback -- run --pptx candidate.pptx --operations sample-edits.json --outdir edit-check-001
```

受管入口遵守管理器的执行开关。示例是核心命令，不能用于绕过停用配置。

操作文件是数组。`slide`、`row`、`column` 从 1 开始，`name` 必须是候选中唯一的实际对象名称。当前任务给出可选对象；先核对实际值，再填写不同的新值。支持的字段由 describe 从实际合同输出，无关字段会被拒绝。

```json
[
  {"op":"text.set","slide":1,"name":"实际文本对象ID","text":"用于抽查的新文字"},
  {"op":"shape.fill","slide":1,"name":"实际形状对象ID","color":"FF00FF"},
  {"op":"table.cell","slide":1,"name":"实际表格对象ID","row":1,"column":1,"text":"抽查值"}
]
```

只保留当前文件适用的操作。执行需要 Windows、PowerPoint 和 pywin32；输出目录必须不存在。程序只修改新副本，保存关闭后重开读回，并导出抽查页。拒绝未改变值的操作，不关闭用户其他文档，不退出 PowerPoint 应用。

`edit-readback.json` 的 passed 只表示已抽查值在保存重开后匹配。必须查看导出图，再使用现有任务的 actions/files 提交实际操作和副本。数据图表和复杂路径需要另行检查。长文案另看 `longer_text_layout`，图片另看几何、裁切、对象身份和媒体读回结果。不自动写入验收状态。

## 图片变换与替换

`picture.transform` 使用幻灯片坐标，单位为 PowerPoint 点。`expected` 填原值，`value` 填目标值，两者均包含 `left`、`top`、`width`、`height`、`rotation`。数值必须有限，绝对值不超过 100000，宽高为正，旋转范围为 `[0,360)`。`aspect_ratio=preserve` 保持宽高比，`free` 允许显式改变比例。前置值与源文件不符时拒绝操作。

```json
[
  {
    "op": "picture.transform", "slide": 1, "name": "photo",
    "units": "slide_points", "aspect_ratio": "preserve",
    "expected": {"left": 90, "top": 90, "width": 160, "height": 100, "rotation": 0},
    "value": {"left": 110, "top": 100, "width": 200, "height": 125, "rotation": 0}
  }
]
```

支持顶层图片及单层无旋转、无翻转的组内图片。组内操作通过父组的偏移和缩放换算幻灯片坐标。嵌套组、旋转组或翻转组在写副本和启动 Office 前拒绝，不把组内图片移到顶层。父组发生非等比缩放时，组内图片的原旋转和目标旋转均须为 0；带旋转的图片暂不支持这一组合。

`picture.replace` 保留原图片的 OOXML 对象节点、ID、组归属和层级，为目标图片建立独立媒体关系，随后由 Office 保存重开。替换不会删除再建对象，也不会覆盖其他对象共享的媒体。

```json
[
  {
    "op": "picture.replace", "slide": 1, "name": "photo",
    "image": "replacement.png",
    "image_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "expected_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "crop_policy": "preserve", "fit_policy": "stretch"
  }
]
```

示例哈希仅占位，调用前分别填入新素材和当前图片媒体的真实 SHA-256。`image` 必须是源 PPTX 所在目录内的相对路径，仅支持 PNG/JPEG，拒绝绝对路径、越界和符号链接或目录联接。`crop_policy` 为 `preserve` 或 `reset`，分别保留或清除原裁切。当前 `fit_policy` 仅支持显式 `stretch`，按原图片框拉伸；素材宽高比不同时需自行决定是否接受变形。工具不自动选择 contain 或 cover。

`picture.crop` 不能与 `picture.transform` 或 `picture.replace` 放在同一批操作中，即使针对不同图片也需分次执行。先在独立副本完成一项，再以其保存输出为输入执行下一项，并重新读取前置值。带扩展 blip 效果的图片暂不支持替换，新素材解码后不超过 1600 万像素。

图片读回核对点坐标、尺寸、旋转、裁切、组归属、层级、对象 ID 和解码后的 RGBA 像素，并检查邻近对象。媒体字节哈希变化不能单独证明换图成功。透明像素读回仍需结合导出图检查外观，GUI 拖动和更换图片另作验证。

## 字号与长文本

`text.set` 可选 `font_size_pt`，取值为有限数值且满足 `0 < font_size_pt <= 400`。文字相同时可以只修改字号，未提供该字段时沿用原行为。保存重开后，收据另给出 `actual_font_size_pt` 和 `font_size_matches`，字号不匹配不能通过内容读回。

```json
[{"op":"text.set","slide":1,"name":"title","text":"同一条待验证的长句","font_size_pt":46}]
```

`longer_text_layout` 分别记录 `within_frame`、`overflow_detected` 或 `not_assessed`。属性读回、几何排版警告和实际看图需要分别报告。历史失败的替代关系见[可靠性与恢复](reliability-and-recovery.md)。调用前用当前安装入口的 describe 核对支持的操作。

## 定向返修

审查任务给出 findings 建议字段。记录对象 ID、实际偏差、待验证原因、拟修改属性和复查范围。先修同类原因，再检查区域外变化。已有 findings 格式继续兼容，不新增一套审查表。
