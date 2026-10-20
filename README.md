# PPT Toolbox

本地 PPT 项目工具箱，为制作 Agent 提供受管工具，集中管理项目、素材、制作进度和交付文件。Windows 1.28.0 已发布，Mac 提供 Apple Silicon 安装试用版。

本仓库以后用于发布软件安装包、发行说明、校验文件和自动更新材料。完整开发源码在私有仓库维护。

## 下载

| 平台 | 当前版本 | 安装包 | 使用范围 |
| --- | --- | --- | --- |
| Windows x64 | 1.28.0 正式版 | [下载 Setup](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.0/PPTToolbox-1.28.0-Setup.exe) | Electron 桌面、项目管理、制作 Agent 接入和 Windows PowerPoint 工具 |
| macOS Apple Silicon | 1.28.0 试用版 | [下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.28.0-20261020/PPTToolbox-1.28.0-arm64-trial.dmg) | macOS 14 及以上，先测试安装、启动、设置、主题和项目界面 |
| macOS Intel | 暂无安装包 | 暂未发布 | 等待后续构建与验证 |

Mac 试用包采用临时签名，尚未经过 Apple 公证，PowerPoint 编辑接口尚未实现，稳定版自动更新关闭。安装步骤和限制见 [Mac 安装指南](manager_docs/MACOS_INSTALLATION.md)。

[Windows 发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.28.0) · [Mac 试用版发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.28.0-20261020) · [所有版本](https://github.com/sj18259360196-source/PPTToolbox/releases) · [平台功能对照](manager_docs/PLATFORM_SUPPORT.md)

## Windows 安装与升级

运行 Setup，按提示选择程序、管理数据与项目位置。1.28.0 内置 Electron 和 Python，桌面已迁移到 Electron；Windows 启动入口需要 .NET Framework 4.6.2 或更新版本。PPT 制作、Office 渲染和编辑验收需要本机 Microsoft PowerPoint。

默认程序目录为 `%LOCALAPPDATA%\Programs\PPTToolbox`，管理数据保存在 `%LOCALAPPDATA%\PPTToolbox`，新项目默认位于文档目录的 `PPTToolbox\Projects`。升级沿用已保存的位置、项目、设置和授权，并保留恢复备份。

安装后，在设置页接入制作 Agent 的 MCP，刷新客户端并验证连接。随后从概况页复制启动指令，与参考图和需求一起发给 Agent。详细步骤见 [桌面安装与接入](manager_docs/DESKTOP_INSTALLATION.md)。

## 日常功能

- 管理项目、文件夹与子项目，调整顺序，批量交付、归档和恢复。
- 查看工作阶段、分支、实际调用和文件变化，追踪异常与结果待确认事项。
- 按制作设置选择原生对象、现有素材或参考生成，查看全页与关键局部，完成编辑和保存重开验证。
- 查询随包经验、指令模板和 MCP 工具。已有用户覆盖与停用设置优先，项目按当前要求独立验收。
- 可选驻留 PPTAgent 通过 Responses API 整理记录与展示工作图，按已有规则处理管理事项。

上述制作流程以 Windows 版为准。Mac 试用范围见 [平台功能对照](manager_docs/PLATFORM_SUPPORT.md)。制作方法见 [看图与修订](references/multipage-efficiency.md)、[素材规则](references/asset-policy.md) 和 [插画调用指南](references/illustration-agent-guide.md)。

## 软件更新与校验

Windows 1.21.1 及之后的版本可在版本与更新页检查、下载和安装，也可直接运行最新完整 Setup。安装前核对更新清单签名及 SHA-256；有活动任务时等待，保留项目、设置和权限。更早版本可手动安装当前正式版。

Windows 正式版与 Mac 试用版分开发行。Mac 试用版不会替换 Windows 稳定更新入口，后续试用包请从 Releases 手动下载。

每个发行页面提供 `SHA256SUMS.txt`。Windows 可使用 `Get-FileHash`，Mac 可使用 `shasum -a 256` 核对下载文件。校验步骤见 [版本与更新](manager_docs/VERSIONS.md)。

## 历史公开源码

仓库保留已有的 **1.27.15** 公开源码快照及其历史，后续应用源码不再同步到这里。Windows 安装包和 Mac 试用包已使用 **1.28.0**。GitHub 自动生成的 Source code 归档对应标签指向的旧公开源码，不能用于构建 1.28.0 或 Mac 试用包。

第三方依赖所需的许可证和源码材料继续按许可要求提供。个人项目、数据库、API 配置、签名私钥和原始反馈不随公开仓库分发。

[使用说明](manager_docs/USER_GUIDE.md) · [Agent 接入](manager_docs/PPTAGENT.md) · [项目管理](manager_docs/PROJECT_MANAGEMENT.md) · [更新记录](CHANGELOG.md) · [反馈问题](https://github.com/sj18259360196-source/PPTToolbox/issues)

本仓库已公开的原创程序代码采用 MIT 许可证。第三方依赖与素材保留各自许可和署名要求，见 [第三方声明](THIRD_PARTY_NOTICES.md)。