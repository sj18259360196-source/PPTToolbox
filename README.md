# PPT Toolbox

本地 PPT 与矢量项目工具箱，为制作 Agent 提供受管工具，集中管理项目、参考文件、制作过程和交付文件。Windows 稳定版为 1.30.2，Mac Apple Silicon 独立测试版为 1.30.2。

本仓库提供安装包、发行说明、更新清单、校验文件和必要的第三方许可材料。新版应用源码在私有仓库维护。

## 下载

| 平台 | 版本 | 安装包 | 使用范围 |
| --- | --- | --- | --- |
| Windows x64 | 1.30.2 | [下载 Setup](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.30.2/PPTToolbox-1.30.2-Setup.exe) | Windows 稳定渠道，桌面管理、制作 Agent 接入与 Windows PowerPoint 工具 |
| macOS Apple Silicon | 1.30.2 测试版 | [下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.2-20261024/PPTToolbox-1.30.2-arm64-trial.dmg) | macOS 14 及以上，临时签名、未公证，手动安装更新 |
| macOS Intel | 暂无安装包 | 暂未发布 | 等待构建与验证 |

[Windows 1.30.2 发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.30.2) · [SHA-256 校验文件](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.30.2/SHA256SUMS.txt) · [所有版本](https://github.com/sj18259360196-source/PPTToolbox/releases)

[Mac 1.30.2 测试版说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.30.2-20261024) · [Mac 测试与反馈](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.2-20261024/MACOS_TESTING.md)

## Windows 1.30.2

矢量空间提供独立的实验性制作入口。开启后复制完整提示词并签发 VEC 编号，由已接入的制作 Agent 读取冻结设置、提交几何文档、导出文件，再登记检查和交付。项目授权与受管执行设置继续生效。

已有矢量项目与 PPT 共用项目页，可搜索、分类、排序、整理、归档和恢复。矢量工作台提供运行路径、项目文件、制作记录和助手摘要四个页签；不同版本分别保留失败、检查与交付记录。默认打开最近一次交付对应的版本，有更新版本时单独提示。

运行路径显示冻结设置、所选版本和全项目当前服务三组记录。结构检查、逐格式导出、返修、部分交付、结果恢复及文件异常都有对应状态。管理助手的排队、处理、过期和失败按实际记录显示；助手只处理管理摘要与备注，不代替制作或交付检查。

桌面运行时更新至 Electron 44.9.3，包含受影响中间证书的撤销修复及同主线安全回补。修正发行包的图标缓存匹配，首次进入素材库可直接加载随包缓存。

## 输出和验收范围

SVG 保留矢量对象和文字，文字依赖接收电脑上的字体。PNG 用于查看预览。Illustrator 兼容选项输出 SVG，原生 AI 与 CDR 导出尚未实现。EPS 仅支持不透明纯色路径，PSD 使用像素图层。矢量 PDF 取决于运行时依赖，标准公开运行时不内置其转换依赖。

导出、结构检查、Agent 看图声明与目标编辑器的打开编辑分别记录。文件生成成功不能证明 Adobe、CorelDRAW 或其他编辑器已经验收。矢量入口关闭后，已有项目仍可查看、整理和管理文件；重新制作须开启入口并满足权限条件。

## 安装与更新

Windows 运行 Setup，可选择安装位置。升级沿用已有管理数据、项目位置、设置和授权。程序内置 Electron 与 Python，启动入口需要 .NET Framework 4.6.2 或更新版本，PPT 制作和 Office 验收需要本机 Microsoft PowerPoint。程序打开时检查更新，确认后下载、校验和安装，有活动任务时等待。更新清单使用签名与 SHA-256 校验；安装器未提供 Microsoft Authenticode 证书，Windows 可能显示未知发布者提示。

Mac 1.30.2 测试版带入当前共享界面、PPT 与矢量项目工作台和制作说明。将 DMG 中的应用拖入 Applications 后启动。测试包使用临时签名，尚未 Apple 公证，采用手动安装更新。正式外置 Agent 监督流程仍要求 Developer ID。安装、完整界面流程、Agent 连接和 PowerPoint 实际操作需要在目标 Mac 上测试，反馈步骤见 [Mac 测试说明](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.2-20261024/MACOS_TESTING.md)。

发行页提供 `SHA256SUMS.txt`。Windows 可用 `Get-FileHash` 核对下载文件，Mac 可用 `shasum -a 256`。

## 历史源码与反馈

本仓库保留 1.27.15 公开源码及历史。GitHub 自动生成的 Source code 归档对应历史应用源码，不能用于构建新版安装包。第三方依赖所需的许可与对应源码继续随发行提供。个人项目、数据库、API 配置、签名私钥和原始验收记录不公开分发。

[使用说明](manager_docs/USER_GUIDE.md) · [矢量项目说明](manager_docs/VECTOR_SPACE.md) · [平台功能对照](manager_docs/PLATFORM_SUPPORT.md) · [Windows 安装](manager_docs/DESKTOP_INSTALLATION.md) · [Mac 安装](manager_docs/MACOS_INSTALLATION.md) · [问题反馈](https://github.com/sj18259360196-source/PPTToolbox/issues)

本仓库已公开的原创程序代码采用 MIT 许可证。第三方依赖与素材保留各自许可和署名要求，见 [第三方声明](THIRD_PARTY_NOTICES.md)。

