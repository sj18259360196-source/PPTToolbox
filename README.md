# PPT Toolbox

本地 PPT 与矢量项目工具箱，为制作 Agent 提供受管工具，集中管理项目、参考文件、制作过程和交付文件。Windows稳定版为1.31.20，Mac Apple Silicon 独立测试版为 1.30.3。

本仓库提供安装包、发行说明、更新清单、校验文件和必要的第三方许可材料。新版应用源码在私有仓库维护。

## 下载

| 平台 | 版本 | 安装包 | 使用范围 |
| --- | --- | --- | --- |
| Windows x64 | 1.31.20 | [下载 Setup](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.31.20/PPTToolbox-1.31.20-Setup.exe) | Windows 稳定渠道，桌面管理、制作 Agent 接入与 Windows PowerPoint 工具 |
| macOS Apple Silicon | 1.30.3 测试版 | [下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.3-20261025/PPTToolbox-1.30.3-arm64-trial.dmg) | macOS 14 及以上，临时签名、未公证，手动安装更新 |
| macOS Intel | 暂无安装包 | 暂未发布 | 等待构建与验证 |

[Windows 1.31.20发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.31.20) · [SHA-256 校验文件](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.31.20/SHA256SUMS.txt) · [所有版本](https://github.com/sj18259360196-source/PPTToolbox/releases)

[Mac 1.30.3 测试版说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.30.3-20261025) · [Mac 测试与反馈](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.3-20261025/MACOS_TESTING.md)

## 安装

### Windows

1. 从上表下载 `PPTToolbox-1.31.20-Setup.exe`。
2. 双击运行，选择安装位置并完成安装。升级时可直接安装新版，软件会沿用已保存的数据、项目位置、设置和授权。
3. 启动 PPT Toolbox，从顶部的**新手教程**开始操作。

安装包已内置 Electron 和 Python，普通使用无需另装 Node.js、npm 或 Python。Windows 启动入口需要 .NET Framework 4.6.2 或更新版本；制作和检查 PPT 需要本机安装 Microsoft PowerPoint。详细步骤见 [Windows 安装说明](manager_docs/DESKTOP_INSTALLATION.md)。

### Mac Apple Silicon 测试版

1. 确认使用 M 系列 Mac，系统为 macOS 14 或更新版本。
2. 从上表下载 DMG，打开后把 PPT Toolbox 拖入 Applications。
3. 启动应用，按 [Mac 测试说明](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.3-20261025/MACOS_TESTING.md) 完成接入与测试。

Mac 当前为独立的 1.30.3 测试版，使用临时签名，尚未经过 Apple 公证，采用手动下载安装更新。平台能力见 [功能对照](manager_docs/PLATFORM_SUPPORT.md)。

### 关于 npm 和命令行安装

npm 是 Node.js 的包管理工具。本项目中的 npm 用于桌面端的开发依赖，普通用户直接下载安装包即可。

目前没有提供 npm、npx、pip、Homebrew、winget 或 Chocolatey 的官方安装方式。GitHub 的 **Code → Download ZIP** 和发行页自动生成的 **Source code** 是历史源码归档；安装当前版本请使用上表的 Setup 或 DMG。

## 第一次制作 PPT

以下按 Windows 1.31.20 的界面说明。先准备参考图片和一个能访问本机 MCP 或运行本机命令的 Agent，例如 Codex、Claude Code、CodeBuddy 或 Qoder。

1. **接入 Agent**。点击左侧 **Agent 接入**，在上方点击 **复制通用接入提示词**，粘贴到 Agent 对话并发送。等 Agent 返回连接结果后，可在工具箱中点击 **检查接入结果**。下方的整理助手为可选功能，第一次制作无需配置助手 API。
2. **保存项目目录**。进入 **制作准备 → 修改目录设置**，点击项目目录旁的 **浏览**，选择用于长期存放 PPT 项目的文件夹，再点击 **保存设置**。参考图、制作版本、预览和交付文件会归入各自的项目文件夹。
3. **选择档位并复制制作提示词**。回到 **制作准备**，选择极速版、标准版或精修版，再复制本次制作提示词。精简版和完整版共用制作要求，区别在说明展开的程度；日常可先用精简版，Agent 容易漏步骤时可尝试完整版。
4. **把提示词和参考图发给 Agent**。在同一个对话中发送制作提示词、参考图片及具体需求，例如哪些文字要改、哪些部分需要内部可编辑。教程中也可复制参考图片试做。若项目出现待审批申请，在工具箱中核对路径后批准。
5. **查看进展与成品**。打开左侧 **项目**，进入已登记的项目，可查看参考图、PPT 预览和制作过程。点击 **打开 PPT** 继续编辑；在 **运行路径** 旁的 **项目文件** 中查找文件，最终成品位于项目的 `delivery` 目录。后续修改可在原 Agent 对话中继续提出要求，并沿用原项目编号。

| 档位 | 适合的任务 |
| --- | --- |
| 极速版 | 图表、表格和简单排版，优先批量制作与合格素材复用。默认开启首版优先提交，先交付内容齐全的首版，再按反馈调整；已记住的关闭选择继续生效 |
| 标准版 | 日常文字、图片和图表混排 |
| 精修版 | 复杂组件、字体和关键局部需要深入处理的任务 |

制作速度会随页数、参考图复杂程度和 Agent 能力变化。可编辑范围取决于所选要求与具体元素，照片和复杂插画可作为独立图片保留。

**卡在某一步时**，新手教程中的关键操作可以单独跳过，结束页会保留待处理项，之后可重试或交给 Agent 排查。底部可跳过整个教程，并选择下次不再提示；需要重看时点击顶部 **新手教程**。素材库和经验库可在后续制作中逐步熟悉，完整操作见 [使用说明](manager_docs/USER_GUIDE.md)。

## Windows 1.31.20

标准与精修新项目采用逐元素标注，按原生结构、图片素材、图标图形、基础样式和风险分类。位置图沿用极速版的编号及框选样式，JSON与Markdown逐项给出制作路线、编辑能力和备注。制作Agent按参考图、实际PPT与Office图判断修正，验收继续沿用各档流程。

本版修复完整制作设置在早期小样和整页冻结时被自身场景校验拒绝的问题，也包含自公开1.31.8以来的原生图形文字检查、对齐与表格工具、逐步新手教程和切档草稿修复。极速首版优先默认开启，已记住关闭的选择继续生效。

新手教程按Agent接入、项目目录、制作准备、参考案例和辅助入口逐步聚焦，关键操作可单独跳过，结束页保留待处理项并支持重试。随包版本页、安装与更新说明同步到本次发行。

升级保留原安装位置、管理数据、项目目录和授权，已有项目继续使用冻结合同。完整内容见[本版发行说明](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.31.20)。本次只发布Windows安装包，Mac继续使用独立1.30.3测试版，已有附件保持。

### 既有矢量与项目管理


矢量空间提供独立的实验性制作入口。开启后复制完整提示词并签发 VEC 编号，由已接入的制作 Agent 读取冻结设置、提交几何文档、导出文件，再登记检查和交付。项目授权与受管执行设置继续生效。

已有矢量项目与 PPT 共用项目页，可搜索、分类、排序、整理、归档和恢复。矢量工作台提供运行路径、项目文件、制作记录和助手摘要四个页签；不同版本分别保留失败、检查与交付记录。默认打开最近一次交付对应的版本，有更新版本时单独提示。

运行路径显示冻结设置、所选版本和全项目当前服务三组记录。结构检查、逐格式导出、返修、部分交付、结果恢复及文件异常都有对应状态。管理助手的排队、处理、过期和失败按实际记录显示；助手只处理管理摘要与备注，不代替制作或交付检查。

桌面运行时更新至 Electron 44.9.3，包含受影响中间证书的撤销修复及同主线安全回补。修正发行包的图标缓存匹配，首次进入素材库可直接加载随包缓存。

## 输出和验收范围

SVG 保留矢量对象和文字，文字依赖接收电脑上的字体。PNG 用于查看预览。Illustrator 兼容选项输出 SVG，原生 AI 与 CDR 导出尚未实现。EPS 仅支持不透明纯色路径，PSD 使用像素图层。Windows 矢量 PDF 的适用范围以随包工具与当前任务返回的能力为准；Mac 1.30.3 内置 PDF 1.4 实色路径导出，明确拒绝文字、渐变和不支持的组合透明度。

导出、结构检查、Agent 看图声明与目标编辑器的打开编辑分别记录。文件生成成功不能证明 Adobe、CorelDRAW 或其他编辑器已经验收。矢量入口关闭后，已有项目仍可查看、整理和管理文件；重新制作须开启入口并满足权限条件。

## 更新与校验

Windows 可在 **版本与更新** 页检查、下载并安装新版。下载后会核对签名与 SHA-256，有活动任务时等待。安装器未提供 Microsoft Authenticode 证书，Windows 可能显示未知发布者提示。

发行页提供 `SHA256SUMS.txt`。下载后，可在 PowerShell 中核对 Windows 安装包的摘要。

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath "$HOME\Downloads\PPTToolbox-1.31.20-Setup.exe"
```

Mac 可在终端中核对 DMG 的摘要。

```sh
shasum -a 256 "$HOME/Downloads/PPTToolbox-1.30.3-arm64-trial.dmg"
```

将输出结果与对应发行页的 `SHA256SUMS.txt` 比较；文件不在默认下载目录时，替换命令中的路径。Mac 使用 [测试版发行页](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.30.3-20261025) 的校验文件。Mac 版本的原生编辑、渲染和待适配范围见 [测试说明](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.30.3-20261025/MACOS_TESTING.md)。

## 历史源码与反馈

本仓库保留 1.27.15 公开源码及历史。GitHub 自动生成的 Source code 归档对应历史应用源码，不能用于构建新版安装包。第三方依赖所需的许可与对应源码继续随发行提供。个人项目、数据库、API 配置、签名私钥和原始验收记录不公开分发。

[使用说明](manager_docs/USER_GUIDE.md) · [矢量项目说明](manager_docs/VECTOR_SPACE.md) · [平台功能对照](manager_docs/PLATFORM_SUPPORT.md) · [Windows 安装](manager_docs/DESKTOP_INSTALLATION.md) · [Mac 安装](manager_docs/MACOS_INSTALLATION.md) · [问题反馈](https://github.com/sj18259360196-source/PPTToolbox/issues)

本仓库已公开的原创程序代码采用 MIT 许可证。第三方依赖与素材保留各自许可和署名要求，见 [第三方声明](THIRD_PARTY_NOTICES.md)。
