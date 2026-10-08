# PowerPoint 原生操作手册

## 使用范围与来源

本手册把来源中的实际操作E01—E22和官方对象模型D02—D20区分使用。附带NativePpt.psm1提供常用COM辅助函数；部分高级操作仍需Agent按当前Office编写并测试。包内Windows脚本未经真实Office运行验证，见validation报告。

所有COM几何、字号、线宽均为pt。图片像素、EMU和pt不混用；1pt对应12700EMU，换算只在边界做一次。PowerPoint对象集合一般使用一基索引，scene连接点为零基。不要把Python库的枚举名和值直接搬到COM。

## 原生命令速查

| 操作 | 对象模型入口 | 包内入口或执行要点 |
|---|---|---|
| 新建演示文稿 | Application.Presentations.Add | 专用输出，不复用用户正在编辑的文档 |
| 页面尺寸 | Presentation.PageSetup | 同时设SlideWidth与SlideHeight |
| 添加空白页 | Slides.Add(index,ppLayoutBlank) | 本包常量BlankLayout=12 |
| 文本框 | Shapes.AddTextbox | Add-PptText |
| 文字与局部字形 | TextFrame/TextFrame2/TextRange | 字符范围按完整字符串核对 |
| 基本形状 | Shapes.AddShape | Add-PptShape |
| 圆角等调整柄 | Shape.Adjustments | 当前绑定先测读写，不假定setter语法 |
| 直线 | Shapes.AddLine | Add-PptLine |
| 自动连接线 | Shapes.AddConnector/ConnectorFormat | Add-PptConnector |
| 自由曲线 | BuildFreeform/AddNodes/ConvertToShape | Add-PptPath |
| 编辑路径节点 | Shape.Nodes | 已生成后按节点集合处理 |
| 联合、相交、剪除等 | ShapeRange.MergeShapes | `Merge-PptShapes`；返回后重新获取结果对象 |
| 对齐 | ShapeRange.Align | 确认以幻灯片或选区为参照 |
| 均匀分布 | ShapeRange.Distribute | 不改变原图明确的不等间距 |
| 组合 | ShapeRange.Group | Group-PptObjects |
| 取消组合、组内访问 | Ungroup/GroupItems | 组合是单个顶层对象，但内部仍需统计 |
| 图层 | Shape.ZOrder/ZOrderPosition | 创建顺序与层级都要检查 |
| 复制 | Shape.Duplicate/Copy/Paste | 副本立即改稳定名称，避免ID冲突 |
| 删除 | Shape.Delete | 先收集目标，删除后不访问旧引用 |
| 翻转和旋转 | Shape.Flip/Rotation | 检查可见边界和连接端 |
| 插入图片 | Shapes.AddPicture | Add-PptPicture，LinkToFile=false，SaveWithDocument=true |
| 图片裁切 | PictureFormat.CropLeft等 | `Set-PptPictureCrop`；COM裁切量为点数 |
| 图片填充形状/异形蒙版 | Fill.UserPicture | `Add-PptPictureFillShape` / `Set-PptShapePictureFill` |
| 替换图片 | 删除/插入并恢复几何层级 | 图片对象不等于普通形状的图片填充 |
| 表格 | Shapes.AddTable/Table.Cell | Add-PptTable |
| 原生图表 | Shapes.AddChart2/ChartData | 先小样，再创建和绑定工作簿 |
| 实色填充 | Shape.Fill.Solid/ForeColor | Set-PptSolidStyle |
| 两色渐变 | Fill.TwoColorGradient | Set-PptTwoColorGradient，初始化后设色 |
| 多色渐变 | Fill.GradientStops或OOXML | 色标位置、方向、Alpha分别核对 |
| 描边和箭头 | Shape.Line | 两端箭头必须分别设置 |
| 阴影、发光等 | Shadow/Glow/SoftEdge | 先清多余主题效果，再按原图显式设置 |
| 文本边界 | TextRange.BoundLeft/Top/Width/Height | 记录原始值并结合旋转与渲染判断 |
| 保存与回读 | SaveAs/Presentations.Open | 候选新路径，最终保存后再检查 |
| 导出预览 | Slide.Export | 固定像素尺寸、等待返回、核实新文件与哈希 |

D02说明Shapes入口；其余具体方法见官方资料索引。高级属性名称必须依据当前对象与实际文档核实，不能仅凭本速查表猜参数。

## 操作卡01　文字与几何恢复

适合标题、正文、标签。前置条件是原文和目标框已确定。调用Add-PptText，明确字体、字号、边距、换行、水平与垂直对齐。设置完成后恢复Width/Height并读回。

```powershell
Import-Module './scripts/NativePpt.psm1'
$title = Add-PptText -Slide $slide -Id 'p01.title' -Text '原图标题' `
  -Left 36 -Top 24 -Width 840 -Height 44 -FontSize 28 `
  -EastAsiaFont 'Microsoft YaHei' -Bold
```

检查实际字形首尾、换行、基线及BoundWidth/Height。宽度近零先修几何，不加空格补居中。局部加粗需在完整TextRange.Characters范围上设置，先验证单对象。来源E02/E04/E17。

## 操作卡02　卡片、渐变与主题

```powershell
$card = Add-PptShape -Slide $slide -Id 'p01.card' -Geometry RoundRectangle `
  -Left 36 -Top 100 -Width 280 -Height 170 -Fill 'E8F1FA'
Set-PptTwoColorGradient -Shape $card -Start 'F3F8FD' -End 'A5C8EB' -Direction vertical
```

参数是示例，不是推荐页面配色。先调用渐变方法，再赋两端颜色，实际方向需要渲染确认。既有对象可能继承主题效果，普通形状、自由形状和连接线入口都要检查。不要通过修改全局主题意外改变整套旧页。来源E02/E09/E19。

Scene 中的径向渐变用于原生椭圆时，默认沿形状边界衰减，适合窄椭圆阴影和柔和高光。需要物理圆形衰减时显式设置 `gradient.path="circle"`；还可指定 `shape` 或 `rect`。其他形状仍默认 `circle`。`path` 仅用于径向填充，不能用于线性渐变或轮廓线渐变。透明色标仍与对象的 `fill_alpha` 相乘。窄椭圆的横向和纵向衰减已通过实际 Office 渲染、保存重开验证，复杂路径及偏心焦点仍须逐对象查看。

## 操作卡03　路径与控制点

按最小可见轮廓建立路径边界，避免局部箭头的bbox占满整页。三次曲线命令为C,c1x,c1y,c2x,c2y,endx,endy；线段为L,x,y。

```powershell
$commands = @(
  @('M',40,220),
  @('C',40,160,200,160,200,220),
  @('L',40,220),
  @('Z')
)
$shape = Add-PptPath -Slide $slide -Id 'p01.halfdisc' `
  -Commands $commands -Fill '5C8DBA' -Line ''
```

COM线段必须配msoEditingAuto；显式曲线控制点采用msoEditingCorner。单节点数组也保留二维结构。回读XML确认真正写入的路径与节点数量，再局部看弧线和闭合边。[D04] 来源E17。

## 操作卡04　连接关系与两端箭头

```powershell
$edge = Add-PptConnector -Slide $slide -Id 'p01.relation' `
  -BeginShape $leftNode -EndShape $rightNode -BeginSite 3 -EndSite 1 `
  -BeginArrow -EndArrow -Weight 1.8
```

site是本包零基约定，模块对COM加1。有效连接点取决于形状，调用前核对ConnectionSiteCount。两端箭头表达视觉方向，BeginConnect/EndConnect表达附着关系，两者分别检查。[D05]

不得在最终精确布线后无条件调用RerouteConnections。自由形状宽箭头可更接近参考轮廓，但不会自动跟随节点，需明确维护方式。来源E12/E19。

## 操作卡05　合并形状

复杂开孔、弧带或复合轮廓可使用MergeShapes。先在副本上选取明确的ShapeRange；记录操作类型、主形状、原对象ID和层级。

`MergeShapes(MergeCmd,PrimaryShape)`返回void。执行后按新增对象ID重新获取结果，不继续使用已被替换的引用。Fragment等操作可能产生多个结果，不能默认只出现一个Shape。具体枚举由当前Office类型库或官方定义取得，不猜数字。[D06]

所有填充、线条、孔洞与对象命名重新检查。合并后文字可能失去直接编辑能力，因此不把正文参与布尔形状运算。

## 操作卡06　对齐、分布与组合

Align第二参数决定相对幻灯片或当前范围；Distribute也需确认参照。原图本来不等宽、不等高时保留差异，不能机械均分。[D15/D16]

组件内部调整完成再分组。Group返回新的Shape；组内对象通过GroupItems访问。内部保持清楚命名，不把数百对象全部放进无意义大组。E19将创新图组合，E07/E08的未分组结构则保留维护限制。[D14]

```powershell
$group = Group-PptObjects -Slide $slide -Id 'p01.component' `
  -Names @('p01.icon','p01.value','p01.label')
```

仅选择当前实际存在的对象。组合与取消组合会改变顶层计数，审查需递归统计实际叶对象和非空文本。

## 操作卡07　层级、替换和删除

后创建对象一般在上方。箭头缺失先查是否被容器覆盖。采用ZOrder时先收集目标再单独改层级，避免枚举时集合重排。[D18]

替换图片先记录Left/Top/Width/Height、Rotation、裁切、Name和层级；插入新图片并还原。删除旧对象后立即放弃旧引用。按名称前缀批量删除可能误删正文，E13已有实例。

只关闭本任务拥有的Presentation，不关闭用户其他文稿。不要用taskkill等处理COM失败。

## 操作卡08　嵌入图片与裁切

AddPicture明确LinkToFile=false、SaveWithDocument=true，避免成品依赖外部目录。保持照片等比，选contain或cover；标识通常保留完整轮廓。[D09]

COM的CropLeft/Right/Top/Bottom以未缩放原图的点数度量；python-pptx相应属性使用比例。两种API参数不能直接搬运。[D17]

SVG插入后的结构与编辑能力需实际检查。当前Python场景构建器主动拒绝SVG；通过Office专用入口插入后保留原生文本，必要时再由Office转换图形。转换入口依版本变化，包内不虚构固定ExecuteMso命令。

## 操作卡09　表格

AddTable返回graphic frame/Shape，通过Table.Cell按行列修改。先单元格文字、边距、段落，再设行高；保持内容字符串精度和单位。[D19]

附加网格是补救方案，不等于单元格边框；表格改大小后需同步。复杂合并单元格与样式先做单独测试。包内构建器支持普通矩形表格，不自动重建复杂合并布局。

## 操作卡10　数据图表

AddChart2的返回Shape具有Chart属性；ChartData.Workbook访问前先Activate。不要假定纯COM可在每台机器直接创建全部图型，E09遇到过失败。[D07/D08]

数据联动、坐标范围、图例与默认标题一起验证。包内Python构建器提供line、column、xy三类；更高级图表由专用适配器负责。保存后缓存检查与实际改数据试验都不能省略。

## 操作卡11　Office导出与文本测量

使用render_powerpoint.ps1，输入一个已经保存的PPTX，输出到全新目录。它逐页导出PNG、读取根级文字边界，保存输入哈希与每个PNG哈希。只读回读不改源文件。[D10/D11]

组内对象、旋转文字、表格和艺术字不以简单宽高判断自动通过。脚本记录需要人工/Agent解释的范围，不把这些项目装成完整检测。

Office不可用或导出失败时保留blocked/failed。备用渲染只能提供其自身证据。源文件最后一次改变后，旧PNG和旧检查全部失效。

## 操作卡12　高级能力边界

PowerPoint还提供艺术字、SmartArt、原生公式、EMF/SVG转换、动画与母版等能力。资料未形成覆盖这些功能的完整可复用脚本，本包也不将其伪装为已实现。遇到这类对象，查当前官方文档、做最小样例并保留编辑能力说明。

用户只需要静态参考图复刻时，不自动增加动画、切换效果、交互或新内容。复杂公式不能仅以LaTeX渲染图片代替可编辑公式要求。


## 操作卡13　异形图片蒙版

当参考图中的照片或复杂纹理不是矩形、圆角矩形时，不要先做大矩形图片再拿白块遮。先创建目标形状或自由路径，再把图片作为形状填充。

```powershell
$photo = Add-PptPictureFillShape -Slide $slide -Id 'p01.photo.mask' -Path './assets/photo.png' `
  -Geometry Oval -Left 60 -Top 120 -Width 180 -Height 180

$mask = Add-PptPath -Slide $slide -Id 'p01.photo.freeform' -Commands $commands -Fill 'FFFFFF' -Line ''
Set-PptShapePictureFill -Shape $mask -Path './assets/factory.png'
```

这种方式使外轮廓仍能调整，但内部照片保持位图。Fill.UserPicture在不同Office版本的缩放/对齐行为需要通过实际导出确认；如果画面主体位置不对，优先在素材文件中先做contain/cover裁切，而不是把正文一起裁进去。

## 操作卡14　布尔形状工具

```powershell
$outer = Add-PptShape -Slide $slide -Id 'ring.outer' -Geometry Oval -Left 100 -Top 100 -Width 180 -Height 180
$inner = Add-PptShape -Slide $slide -Id 'ring.inner' -Geometry Oval -Left 130 -Top 130 -Width 120 -Height 120
$ring = Merge-PptShapes -Slide $slide -Id 'ring' -Names @('ring.outer','ring.inner') `
  -Operation Subtract -PrimaryName 'ring.outer'
```

支持Union、Combine、Intersect、Subtract、Fragment。Subtract顺序决定挖掉谁，Fragment可能产生多个结果。MergeShapes会替换原对象，因此合并前记录对象ID/层级，合并后重新命名和设置样式。

常见场景：圆环、月牙、标签尾巴、卡片凹口、异形遮罩和分区组件。布尔运算比“用多个白块遮住”更稳定，也比用一张大PNG更容易继续调整轮廓。

## 操作卡15　裁切与层级

普通图片需要精确裁边时可调用：

```powershell
Set-PptPictureCrop -Shape $picture -Left 4 -Top 2 -Right 6 -Bottom 1
Set-PptZOrder -Shape $picture -Action SendBackward
```

裁切数值是COM里的点数，不是像素比例。替换图片前记录裁切值；重新插图后恢复几何、旋转、裁切和层级。复杂局部素材应尽量在插入前生成干净透明边缘，PPT裁切只解决边界，不会自动去掉背景污染。
