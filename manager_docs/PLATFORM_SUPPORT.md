# 平台功能对照

Windows本次发行是1.31.20，Mac Apple Silicon独立测试版为1.30.3。平台分别构建与验证，选择对应安装包，按同一发行页的SHA-256核对。

| 项目 | Windows x64 | macOS Apple Silicon | macOS Intel |
| --- | --- | --- | --- |
| 安装包 | 1.31.20完整Setup与签名更新清单 | 1.30.3测试DMG，手动更新 | 尚未发布 |
| 桌面与项目管理 | Electron桌面、PPT及矢量项目、文件与历史记录 | 测试包内的共享界面与PPT、矢量工作台 | 无安装验收 |
| 制作Agent | 本机MCP或受管CLI接入，实际客户端连接另行核对 | 临时签名测试包用内置Python直连，正式外置监督流程要求Developer ID | 无安装验收 |
| PowerPoint | 需要本机Microsoft PowerPoint，按当前任务检查页图与编辑 | 已公布1.30.3测试包括副本编辑、裁切、保存重开、主工作流及快速制作 | 尚未验证 |
| Office页图 | 使用随包工具与本机PowerPoint | PowerPoint原生PDF经PDFium转PNG，直接原生PNG和文本边界测量仍不支持 | 尚未验证 |
| 自动更新 | Windows稳定渠道，校验签名与文件摘要 | 测试版手动安装更新 | 无更新包 |
| 系统签名 | 安装器未提供Microsoft Authenticode证书 | 临时签名、未Apple公证 | 无安装包 |

本次1.31.20只发布Windows安装包。Mac的已验证范围来自独立1.30.3测试，不能据此声明Mac已有1.31.20安装、界面或Office结果。不同Office版本、跨平台迁移以及Adobe、CorelDRAW的实际打开和编辑继续按目标环境验证。

SVG、PNG及各导出格式的适用范围由当前运行时能力和本次文档内容决定。Illustrator兼容选项输出SVG，原生AI和CDR导出尚未实现。文件生成、结构检查和目标编辑器验收分别记录。

完整应用源码由私有仓库维护，公开仓库的历史源码归档不能用于构建当前安装包。下载与说明见[版本与更新](VERSIONS.md)、[Windows安装](DESKTOP_INSTALLATION.md)和[Mac测试说明](MACOS_TRIAL.md)。
