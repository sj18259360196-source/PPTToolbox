# 位图转 SVG 与原生路径

项目制作设置中可分别开启分色 Potrace、Inkvec 和新版 VTracer。全局设置只影响之后创建的项目，已发出的提示词和已有项目保留自己的设置。三个开关初始均关闭，制作 Agent 读取有效设置后选用。引擎随正常安装包提供，不依赖开发机 PATH，不在制作时自动联网安装。

先读取 `graphics_vectorizers`，传入当前项目的完整目录。返回项目开关、运行时版本与哈希、工具启用状态、调用模板及手册。`callable` 仅表示这些前置条件就绪，项目仍须通过原有目录授权。旧项目没有相关设置时三个引擎均关闭。用户明确要求开启时，通过 `toolbox_project_settings_update` 保存相应的 `values.vectorization`，不能为完成描边自行扩大设置或权限。

## 选用方法

| 引擎 | 适用输入 | 需要检查 |
| --- | --- | --- |
| 分色 Potrace | 少色平面插画、花卉装饰、需要换底色的填充图案 | 调色板和背景推断、孔洞、细枝和同色区域的复合关系 |
| Inkvec | 更重视轮廓贴合与曲线拟合的平面图 | 官方透明输出仍可能保留内部背景色线条，深色底检查尤为必要 |
| VTracer 新版 | 固定调色板和 cutout 共享边界的彩色描边 | 本次固定版本是 alpha，简化可能删去花丝、小孔或尖角 |

先按输入选一种方法，只有具体缺陷需要比较时再试另一种。照片、纹理和渐变不承诺恢复为少量语义对象。简单规则图标继续优先用原生几何制作。自动分色得到的复合颜色路径，不等于每朵花、每片叶或每片花瓣都已经独立。

## 调用

统一 MCP 入口为 `graphics_vectorize`，也可以使用三个固定引擎入口 `graphics_vectorize_potrace`、`graphics_vectorize_inkvec`、`graphics_vectorize_vtracer`。固定入口省略 `engine`。所有入口执行相同的项目开关、目录授权与工具启停检查，关闭单个引擎后不能改走统一入口绕过。

```json
{
  "project": "<已授权项目完整目录>",
  "source": "<项目内或该项目已授权输入目录中的PNG路径>",
  "engine": "potrace",
  "max_colors": 4,
  "background": "transparent",
  "preset": "ppt",
  "native": true,
  "request_id": "flower-01"
}
```

`crop` 可选，使用原图像素 `[left, top, right, bottom]`。`box` 可选，指定原生片段放置范围 `[x, y, width, height]`；未指定时放在描边图的局部坐标原点。`prefix` 可选，用于片段局部 ID，合并进场景前避免重复 ID。`max_colors` 范围 2 到 16。`background` 使用 `transparent` 或 `original`，`preset` 使用 `ppt` 或 `detail`。透明背景推断结果、输入 Alpha 处理和量化限制以实际返回为准。

受管 CLI 使用 `toolbox_describe` 返回的 `managed_argv_prefix`，追加 `--project <项目> --json <项目内请求文件>`。不要从工具箱内部脚本拼接另一条无授权入口，也不要复制历史安装路径。

输出写入项目 `assets/vectorization/<request_id>`。同一请求重复调用会核对参数、源图哈希、设置版本和已完成产物哈希，返回已有结果。参数、源图或设置变化时选择新的 request_id。不完整或被修改的目录会报错，先检查留下的 request 和 failure 记录，避免重放未知效果。

## 制作 Agent 接续

1. 看源图和真实预览，检查颜色、内孔、细枝、断线、边缘与透明度。需要换底色时同时检查深色底。`visual_review` 和 `office` 初始分别为 `not_assessed`、`not_run`。
2. 需要原生编辑时查看 `native.status`。只有 `created` 才有原生路径草稿。读取 `native.fragment.path`，使用其中的 `objects`，不要把整个工具响应当作场景片段。
3. 原生转换复用工具箱受限 SVG 编译器，把圆弧和二次曲线转换为三次曲线，保留复合路径与孔洞，不另做未经要求的二次简化。超出支持范围时保留 SVG 并报告原生转换限制，不能用 SVG 文件存在代替原生对象完成。
4. 片段进入当前 `region_objects`，或通过 `rebuild_probe`、`rebuild_compare`、`rebuild_adopt` 试用。工具本身不修改主场景、不刷新任务 token、不自动采用，也不自行完成看图审批。
5. 最终以实际 PowerPoint 渲染核对外观，分别验证改色、分组移动与节点编辑。保存后重开，记录仍不能独立编辑的内容。必要时按位置或真实语义进一步拆组。

`native-draft.pptx` 是独立编辑样件，适合先检验路径，不能直接视为整页制作完成。SVG 预览质量、场景结构正确和真实 Office 编辑是不同检查。

## 运行时与许可

固定版本、二进制 SHA256、上游下载地址、许可证和源代码材料保存在 `assets/vectorizers`。发现文件缺失、哈希不符或平台不支持时返回不可用原因，不能回退到同名 PATH 程序或旧 VTracer。制作过程没有下载动作。当前 Windows 运行时与其他平台的支持状态以查询结果为准，不把 Windows 验证写成 Mac 验证。

本次接入不使用前轮测试的第三方 SVG 转 PPTX 项目。原生转换沿用工具箱自身编译器和场景生成器。
