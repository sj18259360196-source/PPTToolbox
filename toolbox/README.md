# Skill与工具箱

工具数量与可用入口以当前注册表、toolbox_context 和 describe 为准。启动、目录及授权先读[当前软件说明](../references/current-desktop.md)。`pptx.editing-structure` 与 `office.group-roundtrip` 见[视觉保真与编辑分组](../references/visual-editing-repair.md)，`experience.search` 与 `office.edit-readback` 见[Codex 重建辅助](../references/codex-assistance.md)。

核心入口为 toolbox.py，日常受管调用使用 MCP 或 describe 返回的参数前缀。机器可读工具注册表为[registry.json](registry.json)，管理器另提供受管流程入口；不要把旧版数量当成当前能力清单。内部库单独登记，不冒充命令。以下为核心参数参考，不用于绕过受管权限。

```text
python toolbox.py tools list
python toolbox.py tools list --query "异形"
python toolbox.py tools show ops.component
python toolbox.py tools show office.merge-pptshapes
python toolbox.py tools show bench.run
python toolbox.py tools check
python toolbox.py tools check --cli
```

默认工作流start→next→submit。直接操作经`ops`路由，评测经`bench`路由；相应脚本也注册为tools run入口。局部任务自动指向相关工具和说明，不需要读全包。

| 类型 | 调用方式 | 边界 |
|---|---|---|
| python | 真实CLI、argv列表 | 不执行模型任意代码；具体依赖仍需安装 |
| powershell | 显式配置优先，其次固定安装位置的 PowerShell 7，再查 PATH | 路径经受管子进程传递；Office 仍需独立探测 |
| powershell_module | Import-Module后具名函数 | 原有NativePpt工具箱，非通用scene→COM编译器 |
| host | 宿主实际看图/生图工具 | handoff准备数据，不虚构工具或模型调用 |
| manual | 读取文档 | 说明和网址不是已执行的下载或生图 |

[经验与工具关联](../references/experience-library.md) · [命令表](COMMANDS.md) · [直接操作](../references/direct-operations.md) · [跨模型评测](../references/cross-model-evaluation.md) · [素材唯一政策](../references/asset-policy.md)。安装无需模型key；真实API评测单独授权。

## 实测衔接补丁

预审衔接补丁阶段曾注册75个工具条目；管理器另提供15个受管流程入口。该阶段新增regions.normalize、preview.render、preview.compare，管理器收录workflow.preview。参见[预审协议](../references/preview-and-handoffs.md)。
