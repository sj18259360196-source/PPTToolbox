# Mac 安装与更新

## 版本与要求

当前为 1.28.1 Apple Silicon 手动安装包，要求 macOS 14 及以上。Intel Mac 暂无本次安装包。

[下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.1/PPTToolbox-1.28.1-arm64-trial.dmg) · [下载校验文件](https://github.com/sj18259360196-source/PPTToolbox/releases/download/v1.28.1/SHA256SUMS.txt) · [发行页面](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/v1.28.1)

本包沿用临时签名方式，尚未 Apple 公证，稳定自动更新关闭。共享界面包含随机项目编号、项目空间显示和批量清理。正式外置 Agent 监督流程要求 Developer ID，当前包不支持该正式接入流程。

## 安装

1. 下载并校验 DMG，双击打开。
2. 将 PPT Toolbox 拖入 Applications。已有同名应用时，先退出并保留旧版本，再替换。
3. 从 Applications 启动。若提示无法验证开发者，先尝试打开一次，再到系统设置的隐私与安全性中为应用选择仍要打开。[Apple 首次打开说明](https://support.apple.com/en-us/102445)。
4. 若提示损坏或出现其他错误，保留错误原文，通过 [Issues](https://github.com/sj18259360196-source/PPTToolbox/issues) 反馈。

管理数据位于 `~/Library/Application Support/PPTToolbox`，不要放在 app 内或安装磁盘中。更新后核对已有设置与项目。

## 下载校验

在 DMG 所在目录运行，并与发行页 `SHA256SUMS.txt` 中同名文件比较。

```bash
shasum -a 256 PPTToolbox-1.28.1-arm64-trial.dmg
```

## 功能与验证范围

本次包含原生依赖、签名后缓存检查、PowerPoint SDEF 跨作用域解析、诊断脱敏和原生步骤进度修订。最终 DMG 在云端原生 Mac 检查运行时、签名完整性及桌面启动；这些检查与用户机器上的安装、Office 编辑和视觉验收分别记录。

八类 Office 编辑路径已有实现，实际编辑、保存重开和视觉效果仍需实机验收。原生对象新建和局部富文本等能力尚未完成。需要验证 Office 时先运行独立样例，保留首次失败、回执和 PNG。超时后先检查 PowerPoint，避免立即重复写入。

```bash
"/Applications/PPT Toolbox.app/Contents/Resources/runtime/bin/python3" -E -s -B \
"/Applications/PPT Toolbox.app/Contents/Resources/app/distribution/macos/office_smoke.py" \
--run-office --output "$HOME/Desktop/PPTToolbox-Office-$(date +%Y%m%d-%H%M%S)"
```

反馈应包含芯片、macOS、应用和 PowerPoint 版本、操作步骤与错误原文。不要公开上传 API 密钥、管理数据库或私人项目。

[平台功能对照](PLATFORM_SUPPORT.md) · [版本与更新](VERSIONS.md) · [返回首页](../README.md)
