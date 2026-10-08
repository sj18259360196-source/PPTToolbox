# 官方技术与资源索引

核对日期2026-09-16。以下为外部补充，不是22份历史记录全部调用过的工具。仅依据官方文档确认接口/入口；版本、权限和运行行为仍以当前环境实测为准。

未取得完整正文或未确认的接口不纳入已核对清单。文档存在不等于本包完成对应功能的运行测试。

| ID | 文档 | 使用范围 |
|---|---|---|
| D01 | [Agent Skills specification](https://agentskills.io/specification) | 标准目录与frontmatter、按需加载 |
| D02 | [PowerPoint Shapes](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shapes) | 原生对象创建入口 |
| D03 | [AddTextbox](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shapes.addtextbox) | 文本框参数与点数单位 |
| D04 | [FreeformBuilder.AddNodes](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.freeformbuilder.addnodes) | line/curve、auto/corner及控制点 |
| D05 | [ConnectorFormat](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.connectorformat) | 自动附着与连接关系 |
| D06 | [ShapeRange.MergeShapes](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shaperange.mergeshapes) | 合并操作、PrimaryShape与void返回 |
| D07 | [Shapes.AddChart2](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shapes.addchart2) | 原生图表创建 |
| D08 | [ChartData.Workbook](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.chartdata.workbook) | Activate后访问数据工作簿 |
| D09 | [Shapes.AddPicture](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shapes.addpicture) | 嵌入图片与链接参数 |
| D10 | [Slide.Export](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.slide.export) | 导出文件及像素尺寸 |
| D11 | [TextRange.BoundWidth](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.textrange.boundwidth) | 文本实际边界 |
| D12 | [ParagraphFormat.SpaceWithin](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.paragraphformat.spacewithin) | 段落行距参数 |
| D13 | [MsoAutoShapeType](https://learn.microsoft.com/en-us/office/vba/api/office.msoautoshapetype) | 具名形状枚举 |
| D14 | [ShapeRange.Group](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shaperange.group) | 组合对象与计数变化 |
| D15 | [ShapeRange.Align](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shaperange.align) | 选区或幻灯片对齐 |
| D16 | [ShapeRange.Distribute](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shaperange.distribute) | 对象分布 |
| D17 | [PictureFormat.CropLeft](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.pictureformat.cropleft) | COM裁切单位与原始尺寸 |
| D18 | [Shape.ZOrder](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shape.zorder) | 层级操作 |
| D19 | [Shapes.AddTable](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.shapes.addtable) | 原生表格创建 |
| D20 | [python-pptx charts and shapes](https://python-pptx.readthedocs.io/en/latest/user/charts.html) | 图表创建、类别数据与XY数据 |
| D21 | [Lucide license](https://lucide.dev/license) | 图标许可核对入口 |
| D22 | [Tabler Icons](https://tabler.io/icons) | 图标资源入口 |
| D23 | [Material Symbols guide](https://developers.google.com/fonts/docs/material_symbols) | 符号样式与SVG资源 |
| D24 | [Iconify icon sets](https://iconify.design/docs/icons/icon-set-basics.html) | 图标集元数据、许可按集合管理 |
| D25 | [OpenAI Build skills](https://learn.chatgpt.com/docs/build-skills) | Codex本地目录与显式调用；由developers.openai.com/codex/skills重定向 |
| D26 | [python-pptx shapes API](https://python-pptx.readthedocs.io/en/latest/api/shapes.html) | 本包构建接口与分组/连接 |
| D27 | [MsoArrowheadStyle](https://learn.microsoft.com/en-us/office/vba/api/office.msoarrowheadstyle) | 两端箭头具名常量 |
| D28 | [MsoEditingType](https://learn.microsoft.com/en-us/office/vba/api/office.msoeditingtype) | 曲线路径节点类型 |

v1.3新增bench run显式授权联网入口，默认不调用；当前开发未进行真实模型调用。素材检索与生成仍依赖宿主实际能力和许可。

## v1.3新增核对资料

| ID | 文档 | 范围 |
|---|---|---|
| D29 | [python-pptx tables](https://python-pptx.readthedocs.io/en/latest/user/table.html) | 原生合并与单元格语义 |
| D30 | [python-pptx chart API](https://python-pptx.readthedocs.io/en/latest/api/chart.html) | 轴、系列、图例和图表控制 |
| D31 | [python-pptx text API](https://python-pptx.readthedocs.io/en/latest/api/text.html) | 原生文字样式与边界设置 |
| D32 | [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision) | 多模态输入格式 |
| D33 | [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | 任务化评测、失败记录和独立验证 |
| D34 | [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat) | 显式Chat Completions请求 |

仅按上述资料实现协议，未证明任意服务/模型兼容，也未运行真实付费API。
