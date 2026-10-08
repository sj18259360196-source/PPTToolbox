# v1.2默认使用工具箱

新项目从根目录toolbox.py的start/next/submit开始，见[控制器](workflow-protocol.md)及[工具箱](../toolbox/README.md)。下方为独立脚本/旧项目兼容命令；在受管项目中不要手工改状态或覆盖冻结文件。

# 工具运行说明

## 当前实现边界

本包包含一个可执行的scene→PPTX构建器和一组Windows COM操作工具。它没有图片自动语义解析器；看图与scene生成由宿主Agent完成。COM模块提供原生操作函数，不是通用scene转换器。Artifact Tool、图像生成和外部素材检索由宿主适配，不在包内假设其接口存在。

可执行Python部分使用Python 3.10+、Pillow、NumPy、python-pptx、lxml、jsonschema。Windows原生渲染使用已安装的桌面PowerPoint和PowerShell，不依赖pywin32。权限、Office授权和字体需要当前环境具备。

requirements.txt列最低依赖范围，validation环境文件记录本次实际测试版本。没有声称所有范围内版本均经过测试。安装依赖前遵守宿主和用户许可，不自动执行网络安装。

## 脚本目录

| 文件 | 作用 | 不负责 |
|---|---|---|
| init_project.py | 保存参考副本、读取真实尺寸、创建空scene | 看图与自动拆解 |
| preflight.py | 导入包、发现路径、读取图片尺寸 | 证明COM已可渲染 |
| validate_scene.py | schema、ID、尺寸、参数、依赖校验 | 核对参考图语义 |
| build_pptx.py | scene转原生文本/形状/路径/表格/图表等 | 复刻自动评分、SVG导入 |
| NativePpt.psm1 | COM文本、形状、路径、布尔合并、图片填充/裁切、连接、图片、表格和组合 | 全量Office对象模型封装 |
| native_smoke.ps1 | 原生COM最小功能样例 | 全部功能或视觉认证 |
| render_powerpoint.ps1 | 只读打开、逐页PNG、文字边界、哈希收据 | 视觉结论、保存后修复、全部表格边界 |
| inspect_pptx.py | 包关系、对象、文字、表格与基本图表缓存 | 完整ECMA-376、字体实渲、全碰撞 |
| assets_tool.py | 严格裁切、透明度检测、色键抠图、透明边界裁切、底色预览 | 语义抠图、去字、生图本身 |
| compare_images.py | 单页带标签左右对照、叠加、绝对差与分区MAE | 语义审查与通过阈值 |
| compare_deck.py | 核对当前scene、PPTX、原图与Office PNG，生成全页及必查局部证据 | 自动视觉验收 |
| evidence_contract.py | 证据路径/哈希、必查对象、局部几何覆盖 | 原图语义识别、模型诚实性 |
| package_skill.py | UTF-8 ZIP、清单哈希、标准解压和本地链接检查 | 安装或Office验证 |
| verify_delivery.py | 证据哈希、必需审查状态与页覆盖 | 判断人的视觉或诚实性 |
| run_pipeline.py | 串联已分析scene的构建、检查与可选Office渲染 | 生成scene、自动把review填通过 |

## 最短执行顺序

在Skill根目录运行；所有路径换成用户实际批准的项目路径。示例使用相对路径，不绑定私人磁盘或用户名。

```powershell
python scripts/init_project.py --project ./new-project --ratio 16:9 ./page1.png ./page2.png
python scripts/preflight.py ./new-project/input/slide-001.png --out ./new-project/evidence/preflight.json
```

随后Agent读图、转录、拆解，编辑new-project/scene.json。空scene被校验器拒绝是预期行为，不允许插入原图绕过。

```powershell
python scripts/validate_scene.py ./new-project/scene.json
python scripts/run_pipeline.py ./new-project/scene.json --output-dir ./new-project/build/v001 --office --regions ./new-project/evidence/review-regions.json
```

没有Office的环境先不加--office。run_pipeline即使构建成功也默认退出码3，表示还需完成原图、视觉和编辑审查；它不会自动签发成品通过。

## 分步操作

下列命令在Skill根目录运行。统一使用 `new-project/build/v001/`；不要同时运行自动流水线和分步构建写入同一目录。已有COM候选可直接放入新的运行目录 `candidate.pptx`，跳过build命令，只做对应的inspect、导出、对照和审查。

先根据当前实际参考图生成逐页导出尺寸，不套上一页固定数字。

<!-- phase1:step-commands:start -->
```powershell
python scripts/build_pptx.py ./new-project/scene.json ./new-project/build/v001/candidate.pptx
python scripts/inspect_pptx.py ./new-project/build/v001/candidate.pptx --scene ./new-project/scene.json --out ./new-project/build/v001/audit.json
python -c "import sys; from pathlib import Path; sys.path.insert(0,'scripts'); from evidence_contract import reference_snapshot; from common import write_json; _,refs,_=reference_snapshot(Path('new-project/scene.json')); write_json('new-project/build/v001/render-sizes.json',[dict(index=r['index'],width=r['size'][0],height=r['size'][1]) for r in refs])"
pwsh -NoProfile -File scripts/render_powerpoint.ps1 -Pptx ./new-project/build/v001/candidate.pptx -OutputDir ./new-project/build/v001/office -SizesJson ./new-project/build/v001/render-sizes.json
python scripts/compare_deck.py ./new-project/scene.json --pptx ./new-project/build/v001/candidate.pptx --render ./new-project/build/v001/office/office-render.json --outdir ./new-project/build/v001/comparisons --regions ./new-project/evidence/review-regions.json
```
<!-- phase1:step-commands:end -->

有必查局部对象时，regions文件必须为每个必查对象给出区域与 `object_ids`。格式、映射、逐区审查见[第一阶段修复说明](phase1-fixes.md)。没有必查对象时可省略 `--regions`。对照失败不会发布完成收据；修正后选择新的输出目录，旧证据不覆盖。

单页调试可以单独调用，输出目录不能与整套证据目录相同：

```powershell
python scripts/compare_images.py ./new-project/input/slide-001.png ./new-project/build/v001/office/slide-001.png --outdir ./new-project/build/v001/local-debug --regions ./regions.json --region-scale 2
```

分步路线的review从 `assets/templates/review.template.json`复制到同一个run目录，再填写当前PPTX、scene、对照收据的实际身份和已执行的审查。自动run_pipeline已生成review空模板。不得通过补填哈希把旧审查冒充新审查。

## 图层、样式与构建器支持

build_pptx支持text、shape、line、connector、path、image、table、chart、group。path支持M/L/C/Z，可包含原生三次贝塞尔。表格是普通矩形表格，chart支持line、column、xy并带嵌入工作簿。当前构建器的表格与图表限定在幻灯片根层；组内原生数据对象需要另外测试的适配器，不能默默改成图片。

几何全部来自逻辑画布；样式中的font_size_pt、margin_pt、line_spacing_pt和line_width_pt均已经是pt。文字没有隐式缩字号。默认正文或字体只是缺省起点，Agent应按参考显式设置。

仅支持光栅图片插入。SVG/EMF需要Office或其他已测试适配器，不偷偷转换成PNG。连接线自动附着限定根级text/shape对象，组内跨对象附着、动态路径、复杂Chart格式需专用实现。

PowerShell脚本使用UTF-8 BOM保存，兼顾Windows PowerShell 5.1对中文的读取；实际运行仍需按本机版本做最小样例。

未知对象、字段、非法坐标和不支持格式会报错。不能删掉需求来让测试通过，应选择适配器或在交付中说明未满足的编辑要求。

## Windows原生测试

```powershell
pwsh -NoProfile -File scripts/render_powerpoint.ps1 -ProbeOnly -OutputDir ./probe-v001
pwsh -NoProfile -File scripts/native_smoke.ps1 -OutputPptx ./native-smoke-v001.pptx
pwsh -NoProfile -File scripts/render_powerpoint.ps1 -Pptx ./native-smoke-v001.pptx -OutputDir ./native-smoke-v001-render
```

每个输出目录/文件必须是新的。现有用户正在编辑的目标文件会被拒绝，不自动关闭它。脚本只关闭自己打开的演示文稿，不Quit用户应用或杀进程。可能保留空Office进程，以安全优先。

## 检查与发布

完成review.json并核对证据相对路径与哈希后运行verify_delivery。每条通过记录需要说明和实际文件证据。固定后的成品如果被再次修改，必须重新渲染和审查。

```powershell
python scripts/verify_delivery.py ./new-project/build/v001/candidate.pptx --scene ./new-project/scene.json --audit ./new-project/build/v001/audit.json --render ./new-project/build/v001/office/office-render.json --review ./new-project/build/v001/review.json --comparison ./new-project/build/v001/comparisons/deck-comparison.json --out ./new-project/build/v001/delivery-gate.json
```

只把正确版本复制到delivery，复制后重新核对SHA256。遇到校验器自身要求报告与输出目录分离时按其实际契约处理；这不是PowerPoint或所有验证工具的统一规则。

## 退出码

Python构建、素材、对照工具正常执行为0；检测失败通常为1；输入/运行异常可能为2；交付或流程依赖未完成为3。查看对应JSON和日志，不只看屏幕最后一行。


## v1.1复杂素材与异形工具

```powershell
# 纯色背景生成图转透明
python scripts/assets_tool.py chroma generated.png assets/icon-rgba.png --key FF00FF --tolerance 32 --feather 18
python scripts/assets_tool.py trim-alpha assets/icon-rgba.png assets/icon.png --padding 8
python scripts/assets_tool.py matte assets/icon.png evidence/icon-preview.png --background DCEBFA

# PowerPoint原生异形入口见NativePpt.psm1
# Merge-PptShapes / Add-PptPath / Add-PptPictureFillShape / Set-PptShapePictureFill / Set-PptPictureCrop / Set-PptZOrder
```

这些COM函数在本包Linux验证环境无法实机运行。首次在Windows+PowerPoint使用时先做一个最小页并导出，再批量应用。

## 发布ZIP的检查

```powershell
python scripts/package_skill.py build . ../ppt-reference-rebuild-v1.1.1.zip
python scripts/package_skill.py verify ../ppt-reference-rebuild-v1.1.1.zip
```

上两条命令在Skill根目录执行。使用新ZIP名，不覆盖已有分发包。打包器只处理实际文件、不带字体和密钥。测试最终ZIP时标准解压后再运行pytest，不能只测打包前目录。
