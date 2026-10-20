# Development and releases

The current public source snapshot is 1.27.15. Windows 1.28.0 and the macOS
Apple Silicon 1.28.0 trial are distributed as release binaries; their application
source is not currently public. Automatic GitHub source archives contain the
older public snapshot. See [platform support](manager_docs/PLATFORM_SUPPORT.md)
and [release history](CHANGELOG.md) before choosing a build target.

Changes to this public snapshot must keep its source version accurate. Do not
bump release.json to match a binary whose application source is absent. A version
tag builds only when it matches release.json; other binary release tags skip the
source build and preserve existing release assets.

Use a project-local Python environment. Install `requirements-dev.txt` for the
core tests, and the optional graphics dependencies for graphics tests. Windows
desktop and Office behavior require separate Windows acceptance checks.

`release.json` is the product version source. Run
`python -B scripts/release_info.py sync` after changing it.

Public builds use an audited source export and a fresh pinned embedded runtime.
See `distribution/PUBLIC_RELEASE.md` for the exact commands. Never publish
personal project folders, management databases, credentials, feedback, original
experience notes or local build evidence. Changes under the private development
checkout are not automatically part of the public repository.

CI runs focused deterministic tests and builds draft releases from version tags.
A draft is not available to in-app updates. The maintainer verifies the installer,
signs its metadata with a locally protected private key, uploads the signed
manifest and publishes the tested draft. Do not put the private signing key in
the repository, Actions logs or issue attachments.
# 项目默认能力

维护者要求更新的工具、指令和经验均纳入项目默认能力，随正常版本发布。经验目录全部参与默认构建，不按固定编号筛选。新经验需要保留适用条件、动作、证据范围与限制，并关联有效手册和已注册工具。新增能力同时补充发现入口、测试及发行说明。

构建与公开导出须验证默认经验覆盖当前完整目录。公开方法摘要保留来源归属，个人项目文件与原始私有记录不进入公开包。用户已有覆盖与停用设置继续优先。
