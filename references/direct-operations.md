# 第三阶段直接操作

本手册对应v1.3.0实际代码。所有相对路径均以执行命令的当前目录为准；项目与技能分开，输出目录必须为新目录。下面命令在Skill根目录运行，换位置使用`python "<skill>/toolbox.py"`。这些程序完成指定操作，不自动批准视觉或Office验收。

## 1. 先选择任务级入口

| 遇到的问题 | 命令 | 需要模型提供 | 程序完成 |
|---|---|---|---|
| 不会画异形 | ops components / describe / component | 组件名、bbox、少量参数 | 原生路径、分组、ID与PPTX |
| 几何需要裁切/开孔 | ops boolean | 基本形状、运算、先后关系 | 真实复合路径，不用色块假遮罩 |
| 透明素材替换后过大 | ops asset-layout | 目标主体框、锚点 | Alpha主体测量、文件框映射、三种底色检查图 |
| 字体不同/行宽不符 | ops fonts / font-sheet / font-evaluate | 原文样本、候选字体、原图裁片 | 样张PPTX、Office来源核对、字形边界和左右图 |
| 改局部不应动整页 | ops patch-scene / patch-pptx | 源文件哈希、允许对象、具体操作 | 新版本、变更记录、未涉及内容检查 |
| 局部修好但其他区域变了 | ops regression | 同环境前后图、允许区域 | 区域外差异像素与证据图 |
| 要调用宿主生图 | ops generation-prepare / generation-ingest | 当前素材任务、真实工具产物 | 锁定任务/参考图，检查PNG，生成可提交响应 |
| 组内/单元格文字检查漏掉 | tools run office.inspect-recursive-text | 真实PPTX | Windows COM递归读取原生文字和单元格边界 |

机器可读参数用`--help`和`tools show <id>`查询。原生函数仍保留在[NativePpt模块](../scripts/NativePpt.psm1)。模型无需为了调用常见组件重新编写COM脚本。

## 2. 原生组件

```text
python toolbox.py ops components
python toolbox.py ops describe segmented_ring
python toolbox.py ops component --spec examples/phase3/semicircle.spec.json --canvas 400 260 --outdir work/component-v001
```

8种内置组件的参数如下。未列出的参数会报错，禁止默默忽略。

| recipe | params | 输出与限制 |
|---|---|---|
| flat_semicircle | 空对象 | 上方半椭圆、底部直线；w/h决定高宽，不是胶囊 |
| annular_sector | inner_ratio、start_deg、sweep_deg | 内外弧复合路径；整360度保留真正孔洞 |
| segmented_ring | inner_ratio、segments、gap_deg、start_deg、colors | 各扇区独立填充后组合，中心透明 |
| notched_card | cut_ratio | 右上切角原生多边形 |
| double_arrow | head_fraction、shaft_fraction | 两端显式箭头；不会自动跟随节点移动 |
| feedback_curve | bidirectional | 固定三次曲线与端点；不是自动重新布线 |
| icon_node | label、value、description、icon_asset、icon_source、icon_provenance | 底圆、图标、名称、数字、说明分别可选取；图标可为独立PNG |
| photo_window | asset、source_kind、provenance、mask、cut_ratio | 原生图片加ellipse/round_rect/notched_card几何，不烘焙周围标签 |

通用字段为`id`、`recipe`、`bbox`，可选`params`、`style`、`text_style`、`role`、`evidence`。bbox为xywh；区域任务中单位为局部参考像素，独立scene中为其逻辑单位。字号和线宽始终为pt。角度0沿右侧，正角度顺时针。ID为1—24位ASCII字母数字下划线或短横线，内部子对象使用后缀。

独立操作输出`fragment.json`、`scene.json`、`component.pptx`、`operation.json`。`fragment`用于查看编译后的原生对象；正式任务优先提交简短的components参数，让控制器加前缀和变换。含图片时提供项目相对asset及`--asset-base`。

### 直接提交到区域任务

`region_objects`响应的result现在同时接受objects和components。两者不能重复表示同一对象，也不能重复ID。

```json
{
  "objects": [
    {"id":"value","kind":"text","bbox":[65,86,180,36],"text":"32.5%","style":{"font_size_pt":22,"color":"FFFFFF","align":"center"}}
  ],
  "components": [
    {"id":"metric","recipe":"flat_semicircle","bbox":[40,30,240,120],"style":{"fill":"28789E","line":null}}
  ],
  "source_notes":"仅示例；实际执行须查看当前原图，数字照录",
  "relationship_ids": [],
  "uncertainties": []
}
```

默认绘制顺序为components在前、objects在后，因此独立文字盖在组件之上。背景与连接需要其他层级时，增加`draw_order`数组，按从后到前列出全部顶层组件和对象ID，每个恰好一次。例如`["background","metric","value"]`。程序检查漏项、重复和不存在的ID；不会凭位置猜图层。

## 3. 拼接与布尔运算

```text
python toolbox.py ops boolean --spec examples/phase3/boolean.spec.json --canvas 400 260 --outdir work/boolean-v001
```

支持`union`、`subtract`、`intersect`、`combine`和`fragment`。operands为2—16个rect、ellipse或polygon，顺序明确，subtract从首个形状依次扣除后续形状。孔洞由反向路径表达，周围底色变化后孔仍透明。

此入口使用可选Shapely，椭圆用默认128个边采样，范围24—512，不宣称恢复原始贝塞尔。缺依赖时返回明确错误；可使用现有Office `Merge-PptShapes`，或在获准后安装requirements-optional，不自动下载。Office MergeShapes与此多边形引擎是不同实现，分别验证。

## 4. 原生图片蒙版和透明主体定位

photo_window通过p:pic原生几何和裁切实现。独立scene图片也可加：

```json
{"mask":{"geometry":"ellipse"},"fit":"cover"}
```

自定义mask用`geometry: custom`和0—1归一化闭合M/L/C/Z路径。不能同时给预设geometry和commands，不能用contain来宣称已填满蒙版。修改后图片仍是可替换图片；它的内部景物仍是像素。

```text
python toolbox.py ops asset-layout --image actual-icon.png --target 100 150 120 120 --anchor 0.5 0.5 --alpha-threshold 32 --background E8F3F8 --outdir work/icon-layout-v001
```

输出主体bbox、文件bbox、目标放置框、锚点，以及light/dark/target三张底色图。应使用`image_bbox_xywh`放整张图片，使可见主体对齐`placed_subject_bbox_xywh`。不机械复用旧文件的宽高。Alpha阈值只是几何启发式，不能识别语义主体；透明阴影与光晕可能超出主体框，需要实际查看。完全不透明图片也可测量，但报告会明确没有透明像素。

## 5. 字体校准

```text
python toolbox.py ops fonts
python toolbox.py ops font-sheet --spec examples/phase3/fonts.spec.json --outdir work/fonts-v001
```

字体候选必须来自当前机器。示例使用DejaVu/Liberation，不保证Windows已安装；Windows登记名称也不等于已验证每个中文字形。该命令不导出字体文件。

font-sheet给每个候选生成一页原生样张，同一句原文、相同目标框、不同字体属性，标签在测量区外。候选支持font/font_east_asia/font_size_pt/bold/italic/char_spacing_pt/warp，warp只支持none/textPlain。普通文本优先，固定文案在接受编辑限制时再用艺术字。不要用压缩字距掩盖错误字体。

在Windows实际导出样张，按`font-samples.json`的export_size设置尺寸：

```powershell
& "<skill>\scripts\render_powerpoint.ps1" -Pptx "<fonts-v001>\font-candidates.pptx" -OutputDir "<new-font-office-dir>" -Width 1000 -Height 300
```

再运行：

```text
python toolbox.py ops font-evaluate --reference original-text-crop.png --manifest work/fonts-v001/font-samples.json --receipt actual-font-office/office-render.json --outdir work/font-comparison-v001 --background FFFFFF --tolerance 24
```

核对样张与收据、逐页图哈希和尺寸；输出不拉伸字形的左右图及可见字形边界/宽高比/边缘裁切提示。该测量假设背景接近所给纯色，复杂照片上的文字需另行分割、核对。不是OCR、原字体识别或自动选胜者；必须看笔画、基线、换行和可读性。未取得真实Office收据不会伪造替代结果。

## 6. 表格与图表扩展

scene表格新增`row_heights`、`merges`和`cell_styles`。行高使用逻辑单位，数量与行数一致，总和等于表格bbox高。合并范围`[row0,col0,row1,col1]`使用零基、包含末格。被吞并的单元格必须为空，避免静默丢文字。单元格样式按`{row,col,style}`覆写，保持原生边框，不再附加独立网格线。原生最小文字高度和Office排版仍需实测。

图表新增axes.x/axes.y的minimum/maximum/major_unit/minor_unit/number_format/visible/gridlines/font_size_pt/title；legend_position、chart_title和plot_area；系列line_width_pt/marker/marker_size_pt/smooth。分类X轴不能填写数值范围，数值X用xy；柱形不能设置点标记和平滑。plot_area为归一化xywh，不保证各Office版本完全相同。数据来源和工作簿缓存检查继续保留。

可运行[三页功能样例](../examples/phase3/run_demo.py)查看完整scene。样例数据全部为合成测试数值，不是科研结果。

## 7. 有范围的修改

```text
python toolbox.py ops patch-scene --source current/scene.json --spec approved-patch.json --outdir work/patched-v002
python toolbox.py ops patch-pptx --source current/candidate.pptx --spec approved-pptx-patch.json --outdir work/pptx-v002
```

scene补丁需要base_sha256、allowed_ids（slide/object）、reason和changes。支持set_text、set_runs、set_style、set_adjustments、set_path_commands、move、replace_image、table_cell、chart_data。不改对象成员顺序；组整体移动会同步子对象。混排文本拒绝简单set_text，需显式set_runs。素材替换写来源，图表数据修改写data_provenance。新scene连同依赖保存在新目录，全部旧审查失效。

`set_adjustments` 只修改原生形状的调整参数。圆角矩形采用 `value:[0.06]` 这样的归一化值，半径等于该数值乘以短边。半径已测成区域像素时，可直接使用 `rounded_rect` 组件并指定 `params.radius`，避免把像素、pt 和 OOXML 整数混在一起。

补丁统一使用 `value`。兼容 `set_runs` 的 `runs` 别名和 `move` 的 `delta` 别名，转换前后的字段都写入回执。别名与 `value` 同时出现时拒绝执行，其他未知字段仍拒绝。

`set_path_commands` 仅替换已有原生路径的坐标，命令数量和 `M/L/C/Z` 顺序必须保持一致，不能借局部补丁增加子路径或删除孔。坐标修改后重新构建并查看 Office 导出，检查相交、切线和对象关系。

PPTX补丁保留未涉及ZIP部件字节，支持一个run的单行原生文字、原生形状纯色填充、未分组对象move_pt。通过slide一基页号和唯一对象名称定位，不执行任意表达式。不支持的混排、图表或分组变换明确拒绝，走scene或Office路径。修改后先同步scene预期，再用replace-scene/replace-candidate重新进入审查，不能沿用旧报告。

## 8. 区域外回归

```text
python toolbox.py ops regression --before before.png --after after.png --regions allowed-regions.json --environment-before office-fonts-v1 --environment-after office-fonts-v1 --outdir work/regression-v002
```

regions是原始导出像素xyxy列表，例如`[[30,20,1160,110]]`。前后图片必须同尺寸，不隐式拉伸。默认单通道差阈值12，边界余量2像素，区域外变化比例上限0.001，可显式修改并记录。环境指纹由调用者提供，应包含Office版本、字体和导出设置；只是字符串一致不证明环境真实一致。

输出前后左右图、区域外差异图、像素数、差异外接框。环境缺失或不相同时保留environment_unverified；全页都允许改动则没有可检查的区域外，返回not_applicable。它不是图像质量判定，不能代替当前版本与原设计稿的对照。

## 9. 生图交接

先在region_objects按当前模板提交request_asset，next返回asset_material后：

```text
python toolbox.py ops generation-prepare --project my-project --outdir work/generation-request-v001
```

打开生成任务中的参考图，再由宿主调用真实工具。Python没有内置生图API；该操作不假装能调用宿主，也不会自动向新服务上传私有素材。产物获取后填写producer.template.json的tool_used、model_reported（未知为null）、provenance。检查真实透明，必要时按唯一[素材政策](asset-policy.md)处理色键与边缘。

```text
python toolbox.py ops generation-ingest --project my-project --request work/generation-request-v001/generation-request.json --image actual-transparent.png --producer actual-producer.json --outdir work/generation-ingest-v001
```

核对当前任务与原图哈希、真实PNG格式和有效Alpha，输出response.json。检查三底色与局部匹配后才用toolbox submit提交。ingest不自动批准视觉、不自动把tool_used声明当作已验证的模型身份。

## 10. 递归Office文字读取

```text
python toolbox.py tools run office.inspect-recursive-text -- -Pptx current.pptx -OutputDir new-text-audit
```

读取组合子对象、表格单元格、普通与旋转文字，保留原始边界。只有普通、非分组、未旋转对象做简单尺寸超出提示。旋转、组变换、艺术字和单元格仍要求局部对照，不能把包围框相交等同遮字。源文件只读，不结束用户Office进程。本次Linux发布未实际运行此PowerShell入口。

## 11. 单源文字描边与分组测试

文本 style 的 `text_outline` 接受 `color` 和 `width_pt`，由构建器写入原生文字 `a:ln`。只保留一个文本对象，不创建同文底层副本。字体、字号和描边宽度需实际渲染校准。

```text
python toolbox.py tools run pptx.editing-structure -- --pptx current.pptx --out new-structure.json
python toolbox.py tools run office.group-roundtrip -- --pptx current.pptx --outdir new-group-test --slide 1 --name card_group --dx 12 --dy 6
```

第一项只读检查分组和同父组内重叠同文文本。第二项需要 Windows PowerPoint 和 pywin32，写入新副本，检查组移动及恢复各自保存重开后的所有成员几何，并导出两张图。只关闭工具自己打开的副本，不结束 PowerPoint 应用。具体判断边界见[视觉保真与编辑分组](visual-editing-repair.md)。
