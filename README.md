# PPT Toolbox

本地 PPT 项目工具箱，为制作 Agent 提供受管工具，集中管理项目、素材、制作进度和交付文件。Windows 与 Mac 安装包统一更新至 1.28.1。

本仓库用于发布安装包、发行说明、校验文件和自动更新材料。完整开发源码在私有仓库维护。

## 下载

| 平台 | 版本 | 安装包 | 使用范围 |
| --- | --- | --- | --- |
| Windows x64 | 1.28.1 | [下载 Setup](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.1/PPTToolbox-1.28.1-Setup.exe) | Electron 桌面、项目管理、制作 Agent 接入和 Windows PowerPoint 工具 |
| macOS Apple Silicon | 1.28.1 | [下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.1/PPTToolbox-1.28.1-arm64-trial.dmg) | macOS 14 及以上，临时签名、未公证，手动安装更新 |
| macOS Intel | 暂无安装包 | 暂未发布 | 等待构建与验证 |

[1.28.1 发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.28.1) · [下载校验文件](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.1/SHA256SUMS.txt) · [所有版本](https://github.com/sj18259360196-source/PPTToolbox/releases) · [平台功能对照](manager_docs/PLATFORM_SUPPORT.md)

## 1.28.1 更新

- 每次复制提示词立即生成新随机项目编号，连续复制无需等待 Agent 注册。项目详情和制作设置可复制编号，列表支持按编号检索。
- 已完结和已归档页显示磁盘占用。归档页显示清理状态，可预览后批量清理制作历史，保留成品、素材、项目设置和提示词。
- 项目详情的操作按钮对齐，制作策略摘要放到下一行。共享界面同步导航和启动交互修订。
- Mac 合并原生依赖、签名后缓存保护、PowerPoint 字典作用域解析、诊断和启动进度修订。

## 安装与升级

Windows 运行 Setup，升级沿用已有程序、管理数据、项目位置、设置和授权，并保留恢复备份。程序内置 Electron 和 Python；启动入口需要 .NET Framework 4.6.2 或更新版本，Office 制作与验收需要本机 Microsoft PowerPoint。[安装和接入步骤](manager_docs/DESKTOP_INSTALLATION.md)。

Mac 将 DMG 中的应用拖入 Applications。沿用临时签名方式，尚未 Apple 公证，可能需要在系统设置中允许打开。Mac 稳定自动更新保持关闭，正式外置 Agent 监督流程仍要求 Developer ID。实际 Office 编辑、保存读回和视觉效果待实机验收。[Mac 安装指南](manager_docs/MACOS_INSTALLATION.md)。

## 软件更新与校验

Windows 可在版本与更新页下载安装，也可直接运行完整 Setup。程序检查更新清单签名和 SHA-256，有活动任务时等待。Mac 从本页或 Releases 手动下载新版，单独保留平台签名和验证范围。

发行页提供 `SHA256SUMS.txt`，Windows 用 `Get-FileHash`，Mac 用 `shasum -a 256` 核对下载文件。[版本与更新](manager_docs/VERSIONS.md)。

## 历史公开源码

本仓库保留 1.27.15 公开源码及历史，1.28.1 应用源码在私有仓库维护。GitHub 自动生成的 Source code 归档仍对应旧应用源码，不能用于构建 1.28.1 安装包。第三方依赖所需的许可和源码材料继续提供。个人项目、数据库、API 配置、签名私钥和原始反馈不随公开仓库分发。

[使用说明](manager_docs/USER_GUIDE.md) · [平台功能对照](manager_docs/PLATFORM_SUPPORT.md) · [更新记录](CHANGELOG.md) · [问题反馈](https://github.com/sj18259360196-source/PPTToolbox/issues)

本仓库已公开的原创程序代码采用 MIT 许可证。第三方依赖与素材保留各自许可和署名要求，见 [第三方声明](THIRD_PARTY_NOTICES.md)。
