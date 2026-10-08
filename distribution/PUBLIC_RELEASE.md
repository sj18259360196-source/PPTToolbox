# 发布维护

公开仓库采用经过筛查的源码快照。个人项目、原始反馈、数据库、API 配置、签名私钥和历史验收材料不进入公开快照。首次公开版为 1.21.0，原开发仓库及历史保留。

## 构建

Windows x64 构建机需要 Python 3.11 及以上、.NET Framework 编译器和 Inno Setup 6。依赖安装在项目虚拟环境中。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r distribution/requirements-build.txt
.venv\Scripts\python -m pip install --no-deps --no-build-isolation --only-binary=:all: --no-binary=proxy_tools --require-hashes -r distribution/requirements-release.lock
.venv\Scripts\python -B scripts/release_info.py check
.venv\Scripts\python -B distribution/public_source.py --audit . --report dist/source-audit.json
.venv\Scripts\python -B distribution/build_runtime.py --output dist/runtime --cache .tmp/codex/release/runtime-cache
.venv\Scripts\python -B distribution/build_portable.py --donor dist/runtime --output dist/PPTToolbox-1.21.0
.venv\Scripts\python -B distribution/build_setup.py --bundle dist/PPTToolbox-1.21.0 --compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" --scratch .tmp/codex/release/setup --output dist/setup
```

CPython 来自官方嵌入式 ZIP，版本与 SHA-256 固定。依赖的版本、平台文件与哈希固定，纯 Python 的 proxy_tools 由固定源码包构建。运行环境不借用本机已有安装。构建脚本遇到同名输出会停止，先保留已有交付，再使用新目录。

`build_portable.py --donor` 接受新构建的运行环境目录。这里只把它作为经过清单验证的输入，不要求曾经发布过的软件包。修改依赖后，需重新记录哈希、许可证和来源，并在包内运行 `distribution/runtime_probe.py`。

## 签名与发布

签名私钥独立保存在开发仓库之外，用 Windows DPAPI 绑定维护者的系统账户。首次生成会把公钥写入 `distribution/release_config.json`。配置中的仓库和公钥应在发布前固定。

```powershell
python -B distribution/release_manifest.py init-key --private-key <仓库外的私钥路径>
python -B distribution/release_manifest.py sign --private-key <仓库外的私钥路径> --installer dist/setup/PPTToolbox-1.21.0-Setup.exe --notes distribution/RELEASE_NOTES.md --output dist/signed-update
```

先创建 GitHub Release 草稿。上传安装包、可选便携 ZIP、对应源码材料、`PPTToolbox-update.json`、`PPTToolbox-update.sig.json` 和 `SHA256SUMS.txt`。下载文件并重新核对摘要后再发布。签名只对该安装包有效；重新构建后必须重新签名，不能沿用旧清单。

自动更新固定读取本仓库的最新正式 Release。草稿与预发行版不进入稳定渠道。发布后不替换同版本文件，需要修正时增加版本号。仓库支持时启用不可变发行版，并为维护者账户配置双因素认证。

CI 对普通提交运行测试，在版本标签上构建安装包并创建草稿。工作流只上传未签名候选，维护者核验后用本地私钥签名。私钥不进入 GitHub Secrets 或工作流日志。已有发行版保持原样，重复运行仅保留新的 CI 构建产物。

## 验证范围

发布至少验证签名失败、哈希不符、下载中断、取消重试、活动任务等待、安装文件回滚，以及项目和配置保留。用隔离数据测试新安装，再在允许的时机验证已有安装升级。

CI 测试通过不表示真实 Office 或外部 Agent 已经完成验证。首次公开安装包没有 Microsoft Authenticode 证书，更新清单签名不能消除 Windows 的未知发布者提示。

随包 GEOS 的对应源码与构建材料需作为第三方源码资产一同发布，保留运行环境中的原始许可证与可替换 DLL。素材署名见 `assets/icon-packs/THIRD_PARTY.md`。
