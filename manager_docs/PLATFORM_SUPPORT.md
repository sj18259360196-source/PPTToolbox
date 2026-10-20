# 平台功能对照

截至 2026-10-20，Windows 正式版与 Mac 试用版均为 1.28.0。安装包的功能范围与公开源码版本分别维护。

| 项目 | Windows x64 正式版 | macOS Apple Silicon 试用版 | macOS Intel |
| --- | --- | --- | --- |
| 安装包 | Setup 已发布 | DMG 已发布，要求 macOS 14 及以上 | 暂未发布 |
| 桌面 | 已迁移 Electron | Electron 试用包，桌面交互待实机反馈 | 暂无安装验收 |
| 项目、设置、主题 | 沿用现有功能 | 可作为本轮试用内容 | 暂无安装验收 |
| 制作 Agent、CLI、MCP | 沿用原有工具与接入流程 | 正式外置 Agent 接入要求 Developer ID，当前试用包不支持 | 暂无安装验收 |
| PowerPoint 原生制作、渲染、编辑读回 | 依赖本机 Windows PowerPoint | 编辑接口尚未实现，Office 制作与验收尚未开放 | 尚未开放 |
| 软件更新 | 正式版签名更新清单与完整 Setup | 稳定版自动更新关闭，手动下载试用包 | 暂无更新包 |
| Apple 签名与公证 | 不适用 | 临时签名，未经过 Apple 公证 | 暂无发行包 |

Windows 1.28.0 已完成维护者本机的安装升级、基础启动与数据连续性核对。图片重建、多图制作及全部功能的完整实测仍待验收。

Mac 试用包已完成原生构建、签名前后运行时检查和 DMG 校验，尚未完成用户实际安装与桌面交互验收。跨 Windows 与 Mac 的完整项目迁移也未完成端到端验证。

当前公开源码为 1.27.15。1.28.0 桌面和 Mac 实现暂未公开，公开源码的测试结果对应这一旧快照。

[Windows 安装](DESKTOP_INSTALLATION.md) · [Mac 安装](MACOS_INSTALLATION.md) · [版本与更新](VERSIONS.md)