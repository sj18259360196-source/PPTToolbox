# PPT Toolbox

面向 Windows 的本地 PPT 项目工具箱，为制作 Agent 提供受管工具，集中显示项目、文件、工作路径、交付结果和需要处理的异常。

制作时按[看图与修订流程](references/multipage-efficiency.md)选择整页和局部，查看全页及关键局部的左右对比和叠加图，保留未变范围的有效审查。原生对象与图片的选择遵循[素材规则](references/asset-policy.md)。

项目随包提供经验、指令模板和 MCP 工具。实际可用条目及数量以当前 toolbox_context、工具枚举与经验查询返回结果为准。新安装无需导入开发机历史即可使用这些方法；已有用户覆盖和停用设置仍优先。经验用于指导操作，当前项目仍需独立验证。

## 下载与安装

在本仓库 Releases 页面选择已发布版本的安装包，源码版本可能先于安装包。安装包自带 Python；桌面界面需要 Microsoft Edge WebView2 Runtime 和 .NET Framework，Office 制作与验收功能需要 Microsoft PowerPoint。

程序默认安装在 `%LOCALAPPDATA%\Programs\PPTToolbox`，管理数据保存在 `%LOCALAPPDATA%\PPTToolbox`，新项目默认放在用户文档目录的 `PPTToolbox\Projects`。安装时可更改位置，升级沿用已保存的位置。

安装后，在设置页接入制作 Agent 的 MCP。也可复制接入提示词，让能操作本机的 Agent 配置并验证连接。随后从概况页复制启动指令，与参考图和需求一起发给 Agent。

## 日常功能

- 项目以文字索引显示，支持排序、文件夹、子项目、批量交付和归档。打开项目后再读取工作详情与当前预览。
- 工作路径显示大阶段、分支、实际调用和文件变化，单独显示较大的错误及结果待确认。
- 制作 Agent 在大阶段切换时打卡，软件负责整理界面内的进度。
- 驻留 PPTAgent 为可选功能，通过 Responses API 整理记录、更新展示工作图，并按保存的规则处理管理事项。它不负责软件更新，不获得任意命令执行权限。
- 素材与经验保留来源。个人 API 配置、项目和经验存放在本地；公开版不附带作者的历史项目复盘原文。

制作 Agent 先分析整页背景、分区、层次与文字归属，再逐组件选路。复杂插画与装饰标题在整体编辑满足需求时默认参考局部生成，无需原生试稿或相似度分数。简单插画与规则几何使用原生对象；照片、准确标识和已有清晰素材保留源像素及内部原有文字。页面独立文字保持原生，内部编辑由明确要求触发。

## 软件更新

从 1.21.1 开始，在版本与更新页检查、下载和安装。默认每天自动检查一次，可关闭。下载和安装由用户发起，签名与 SHA-256 校验通过后才能执行。有活动任务时等待，保留原项目、设置和权限。

早期版本（包括 1.21.0）需要先手动安装一次 1.21.1。无法联网时仍可使用当前软件，也可手动下载完整安装包。首个公开安装包尚未使用 Microsoft Authenticode 证书，Windows 可能显示未知发布者提示。

## 开发

源码支持 Python 3.11 及以上。公开 Windows 运行环境与依赖固定在 `distribution/runtime-lock.json` 和 `distribution/requirements-release.lock` 中。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -B manager.py --data-dir ..\PPTToolbox-development-data serve
```

开发数据必须位于源码之外。构建和签名见 [发布维护](distribution/PUBLIC_RELEASE.md)。测试、桌面启动、Office 渲染和外部 Agent 连接分别验证。

[使用说明](manager_docs/USER_GUIDE.md) · [Agent 接入](manager_docs/PPTAGENT.md) · [项目管理](manager_docs/PROJECT_MANAGEMENT.md) · [版本与更新](manager_docs/VERSIONS.md) · [更新记录](manager_docs/CHANGELOG.md)

原创程序代码采用 MIT 许可证。第三方依赖、图标和医学素材保留各自许可与署名要求，见 [第三方声明](THIRD_PARTY_NOTICES.md)。


## 1.26.7 插画方法直接入口

简单分层插画或明确要求内部编辑时，按需调用 graphics_illustration_guide，按实际观察选择钢笔节点或选区转路径，再调用 graphics_route_illustration。指南直接返回当前参数、受管调用入口、步骤和复查条件，不依赖经验检索。保留孔洞与共享边，分别验证轮廓、颜色和编辑行为。详见 [Agent 调用指南](references/illustration-agent-guide.md)。软件图形构造页可读取并复制整套调用步骤；升级后重连 MCP。
