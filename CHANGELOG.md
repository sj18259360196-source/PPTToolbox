# 更新记录

## 2026-10-20 · Mac 1.28.0 试用版

发布 Apple Silicon DMG，要求 macOS 14 或更新系统。已完成 macOS 14.8.9 arm64 原生构建、临时签名、签名前后运行时检查和 DMG 校验。

当前供安装、启动、设置、主题和项目界面试用。尚未经过 Apple 公证，PowerPoint 编辑接口尚未实现，正式外置 Agent 接入仍要求 Developer ID，稳定版自动更新关闭。实际安装与桌面交互待实机反馈，Intel 安装包暂未发布。

[Mac 发行页面](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.28.0-20261020) · [安装指南](manager_docs/MACOS_INSTALLATION.md)

## 2026-10-20 · Windows 1.28.0

Windows 桌面迁移到 Electron，继续使用原有业务界面和 Python 服务。项目管理、制作工具、图形素材、经验指令、Agent 接入、CLI 与 MCP 沿用原实现。

提供 Fluent 轻透、Office 蓝和深蓝工作台主题，统一蓝色 P 图标。升级沿用已有安装目录、管理数据、项目与授权，并保留恢复备份。已完成维护者本机安装升级、基础启动和数据连续性核对，图片重建与多图制作效果仍待验收。

本版发布 Windows x64 安装包及签名自动更新文件。应用源码暂未公开，Source code 归档对应旧公开源码。第三方源码附件沿用上一版公开材料。

[Windows 发行页面](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.28.0)

## 1.27.15 及更早公开源码

当前公开源码快照为 1.27.15。文字校准、编辑验证、素材与项目管理等历史更新见 [详细更新记录](manager_docs/CHANGELOG.md) 和 [源码发行说明](distribution/RELEASE_NOTES.md)。