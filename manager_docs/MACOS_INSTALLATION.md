# Mac 试用版安装

## 版本与要求

当前安装包为 `PPTToolbox-1.28.0-arm64-trial.dmg`，适用于 Apple Silicon 和 macOS 14 或更新系统。Intel Mac 暂无安装包。

[下载 DMG](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.28.0-20261020/PPTToolbox-1.28.0-arm64-trial.dmg) · [下载校验文件](https://github.com/sj18259360196-source/PPTToolbox/releases/download/macos-trial-v1.28.0-20261020/SHA256SUMS.txt) · [发行页面](https://github.com/sj18259360196-source/PPTToolbox/releases/tag/macos-trial-v1.28.0-20261020)

本包采用临时签名，未经过 Apple 公证。本次更新已包含八类 PowerPoint 编辑接口，真实 Office 编辑与视觉效果待实测，外置 Agent 监督进程仍要求正式 Developer ID，当前试用包不支持该正式接入流程。稳定版自动更新关闭。

## 安装

1. 下载 DMG，双击打开。
2. 将 PPT Toolbox 拖到 Applications。已有同名程序时，先退出并保留旧版本，再进行替换。
3. 从 Applications 启动。若提示无法验证开发者，可先尝试打开一次，再到系统设置的隐私与安全性中为该应用选择仍要打开。具体操作见 [Apple 首次打开说明](https://support.apple.com/en-us/102445)。
4. 若提示应用损坏或出现其他错误，保留完整提示，通过 [Issues](https://github.com/sj18259360196-source/PPTToolbox/issues) 反馈。

管理数据应位于 `~/Library/Application Support/PPTToolbox`，不要保存在 app 内或安装磁盘中。

## 下载校验

在 DMG 所在目录打开终端，运行以下命令，并与发行页面的 `SHA256SUMS.txt` 比较。

```bash
shasum -a 256 PPTToolbox-1.28.0-arm64-trial.dmg
```

当前 DMG 的 SHA-256 如下。

```text
fb6593fca0b09cd8143a929873620bf387d2dea8b7cc807f88a9c40841a093a7
```

## 本轮试用

先用测试项目检查启动、设置、三种主题、项目列表和文件定位。退出后重新启动，核对设置与测试项目是否保留。可以使用以下命令进行独立样例编辑试验；真实 Office 结果仍待验收。

```bash
"/Applications/PPT Toolbox.app/Contents/Resources/runtime/bin/python3" -E -s -B \
"/Applications/PPT Toolbox.app/Contents/Resources/app/distribution/macos/office_smoke.py" \
--run-office --output "$HOME/Desktop/PPTToolbox-Office-$(date +%Y%m%d-%H%M%S)"
```

命令会启动 PowerPoint，在桌面新建测试文件夹，编辑自动生成的样例副本。自动化权限询问时允许终端控制 PowerPoint。完成后反馈 smoke-result.json、编辑回执与 PNG；失败时保留终端输出。超时后先检查 PowerPoint，不要立即重试。

安装包已在 macOS 14.8.9 arm64 完成构建、临时签名、签名前后运行时检查和 DMG 校验。实际用户安装、桌面交互和重启后的数据连续性仍待实机反馈。

反馈时提供芯片型号、macOS 版本、应用版本、具体步骤及错误原文。涉及 Office 时补充 PowerPoint 版本。不要在公开附件中提交 API 密钥、管理数据库或私人项目。

[平台功能对照](PLATFORM_SUPPORT.md) · [版本与更新](VERSIONS.md) · [返回首页](../README.md)