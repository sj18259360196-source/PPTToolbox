# 可编辑图标库

图标素材页提供关键词检索、参考图外观检索、SVG 导入、重绘草稿和人工检查。工作台左侧可进入该页面，并保留当前项目。

## 素材与版本

随包精选集包含 Tabler、Lucide、Health Icons 和 Bioicons。准确数量、上游文件和固定提交以 `assets/icon-packs/curated.json` 为准。各文件保留原作者、授权和来源，不推断整个 Bioicons 仓库使用相同授权。

2026-09-28 新增 Phosphor、Fluent System Icons、Material Symbols、Iconoir、Bootstrap Icons、Servier Medical Art 和 Reactome，共 11,824 个可转换素材。新增包位于 `assets/icon-packs/expanded-*.json`，与原有 67 个精选素材共用搜索及版本数据库。通用库采用常用尺寸和样式，未收录上游的全部变体。科研库只收录当前转换器支持且通过 SVG 渲染差异检查的素材。

Material Symbols 使用固定提交的 Iconify 数据文件，作者和素材授权仍为 Google、Apache 2.0。Servier 使用 Bioicons 中标注 CC BY 3.0 的 SVG 版本，保留该版本授权。Reactome 使用官方 SVG 下载包，按下载文件哈希固定来源，保留官方分类名称及 CC BY 4.0 授权。完整许可证位于 `assets/icon-packs/licenses`。

管理器在自己的数据目录中保存 `icon-library/icons.sqlite3`。原始 SVG、标准化 SVG、原生对象配方、预览和来源共同构成不可变版本。修改已有图标会生成子版本。数据库使用事务写入，不覆盖旧版本。

精选素材标记为 curated，自绘与导入标记为 draft。后者需要在界面填写检查说明后晋级 reviewed。精选表示来源经过筛选，不表示该图标已通过所有 Office 场景验收。图标复用时仍需检查具体页面。

## Agent 调用

1. 使用 `icons_search` 按含义搜索。中文名称、英文别名、标签和风格可以组合。
2. 使用 `icons_inspect` 读取部件和来源。科研含义需要核对，不能仅按外形替换。
3. 使用 `icons_fragment` 获取 scene 分组。box 使用目标页面逻辑坐标，points_per_unit 使用 canvas.width_pt / canvas.width，prefix 在页面内唯一。
4. 在当前 region_objects 任务中提交返回的原生分组。来源和固定版本须记录在 evidence 中。
5. 使用 `icons_place` 将原始 SVG、当前样式 SVG、预览、scene 和可编辑 PPTX 固定到已授权项目的 assets/icons 目录。该操作不会改写当前候选或自动推进工作流。

先用 `icons_stats` 读取可用 collection 名称，再按英文概念或中文标签搜索。中文标签覆盖常见概念，不代表每个专业名称都有中文译名；未命中时应尝试英文名称。Reactome 的蛋白、受体和细胞含义需要按官方名称核对。

`icons_inspect` 和 `icons_fragment` 返回 `attribution`，包含作者、来源、许可证地址和转换说明。新生成的项目副本附带 `ATTRIBUTION.txt`；旧副本继续保留。交付 PPT 时，将实际使用素材的署名汇总到来源页或随附清单，注明实际改色、改形等修改。图标详情页也可复制素材署名。

缺少素材时，Agent 在当前项目中绘制原生形状和路径，按语义分组后提交到 `region_objects`。源 SVG 可保存在项目 `assets` 中，转换后的轮廓仍需对照实际 Office 渲染检查。

`icons_redraw_submit`、`icons_trace` 和 `icons_model_generate` 会写入全局素材库，仅供用户界面调用。Agent 不应为当前项目启动这条全局入库流程。作品交付获认可后，通过 `toolbox_retrospective.assets` 记录用户是否保留自绘素材的选择。

`icons_trace` 使用 VTracer 获取轮廓草稿。它不识别语义部件，节点多时需要 Agent 简化。`icons_validate` 记录源 SVG 与转换结果在黑白背景下的像素差异，只提供比较证据。

项目内的细小轮廓可用 `icons_trace_fragment`。先从参考图分离一个明确的语义部件，提供边长 2 至 512 像素的不透明黑白 PNG 蒙版，黑色表示部件，白色表示背景和孔洞。接口接收 `mask` 的 PNG base64、`semantic_name`、目标 `box`、唯一 `prefix` 和可选的六位十六进制 `color`，返回可提交的 `scene_fragment`。该操作不创建全局素材版本。

二值描摹在拟合前进行三倍最近邻采样，以减少细小部件被合并的情况。采样不会增加原图信息，轮廓吻合也不能代替语义或视觉验收。不要将整页或照片量化为碎片路径；渐变与高光应在语义部件上分别绘制，文字保留文本框。

弯曲的插画轮廓可显式选择 `smoothing="curves"`，使用三倍双线性采样后拟合曲线。默认 `none` 保留像素边界。曲线模式可能圆化尖角或影响狭窄部件，返回结果会提示复查；文字、技术符号和像素图应保留原边界。

所有图标操作同时提供受管 CLI 入口。将请求写入 JSON 文件后执行以下命令，其中 DATA 使用 toolbox_context 返回的数据目录。

```powershell
python manager.py --data-dir DATA execute --tool icons.search -- --json request.json
```

MCP 提供图标检索、检查、原生片段和项目放置接口。图标写操作遵循 Agent 执行开关，各工具可独立停用。全局自绘入库接口即使出现在工具列表中，也不代表 Agent 获准调用；执行层会拒绝。人工晋级不通过 MCP 暴露。

## 转换范围

支持 SVG 路径、圆、椭圆、矩形、折线、多边形、分组和变换。二次曲线及椭圆弧转换为三次贝塞尔，保留独立部件、颜色、透明度、线宽、端点和连接样式。简单嵌套的奇偶填充轮廓会调整方向，以保留孔洞。

脚本、外部资源、嵌入图片、文字、滤镜、蒙版、剪裁和未支持样式会被拒绝。自交的奇偶填充需要先整理。请勿将导入失败的图标标记为可编辑。每项导入失败会给出具体原因；批量导入中的其他项目仍可完成。

参考图外观检索使用本地 32×32 灰度描述，不调用外部服务，也不具备语义判断能力。可先用名称或标签限定含义，再进行外观排序。

## 可选本机 SVG 模型

在图标页面配置本机 HTTP 地址，服务收到 POST JSON。

```json
{"prompt":"图标含义及重绘要求","reference":"可选 PNG data URL","format":"svg"}
```

服务返回 JSON。

```json
{"svg":"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\">...</svg>"}
```

适配器可以连接实现该协议的 StarVector 服务。模型权重不会自动下载；没有配置服务时明确报告未配置。仅接受本机地址，禁止重定向。模型生成结果仍经过同一转换器并进入草稿。

## 验证与复用

检查图标轮廓和科学含义后再加入常用库。PowerPoint 验收需要实际打开原生 PPTX，修改组成部件，保存、关闭并重开。源 SVG 对比、Office 渲染对比、编辑读回分别记录。

项目副本带 manifest 和文件哈希，库中后续变化不会改变已有项目。发现项目副本改变或不完整时拒绝覆盖，保留现场检查。

上游资料及依赖授权见 `assets/icon-packs/THIRD_PARTY.md`，重新获取固定素材使用 `distribution/build_icon_pack.py`。
