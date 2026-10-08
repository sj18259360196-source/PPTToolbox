# 第一阶段受管执行

本页只说明已实现接入。六个MCP接口复用 `Manager.execute_workflow` 和 `toolbox_manager/execution.py`。CLI的 `workflow.*` 也进入同一服务及固定worker，不直接从MCP调用workflow函数。

第二阶段四个局部能力也进入此链路。`rebuild_probe/patch/compare/adopt` 的参数及支持边界见[局部重建](local-rebuild.md)，原六接口不变，当前测试状态以phase-02记录为准。

## 接口

| MCP | 原工具 | 参数 |
|---|---|---|
| rebuild_start | workflow.start | project；references数组或scene二选一；candidate、ratio、mapping、office布尔值、builder可选 |
| rebuild_next | workflow.next | project |
| rebuild_submit | workflow.submit | project、task_id、token、result对象；base_revision可选 |
| rebuild_status | workflow.status | project |
| rebuild_revise | workflow.revise | project、slide、reason；region可选 |
| rebuild_finish | workflow.finish | project |

`tools/list` 返回JSON Schema，拒绝未知字段、类型错误和非有限数字。区域对象沿用scene定义，组件沿用已有CATALOG参数。submit还按当前task.kind检查结果。原控制器继续在单写锁内核对token、revision、packet及输入文件哈希。

next会写任务、构建、导出和对照，不能当作只读调用。status只读工作流，管理器仍会写调用日志。工具注解不构成授权。

next返回当前task身份、必看文件、模板、合同、必要context及相关受管工具。经验检索最多保留现有三条，不加载整个库，不调用模型API。程序不填写viewed_files或审查结论。

## 本地授权

管理数据必须在程序包之外。新管理目录默认关闭受管执行，也没有项目目录授权。用户通过管理界面开启执行，并选择手动或自动批准项目请求。`auto_approve_project_requests` 开启时，受管 start 按已保存策略登记本次项目及输入目录并继续执行，保留批准来源和设置修订号。关闭时可在项目页逐项批准，也可明确运行本地所有者命令。

```text
python manager.py --data-dir <manager-data> authorize-project --project <exact-project> --input-root <input-directory>
```

该命令没有MCP或HTTP Agent路由。input-root可重复指定。项目不能包含程序包或管理数据，也不能在它们内部。输出留在项目内，导入输入只接受项目内或明确授权输入根下的文件。拒绝符号链接、Windows重解析点、项目硬链接及NTFS备用流路径。

授权快照由共用服务生成，经固定worker的stdin传递；worker核对父PID和调用标识。普通工具参数不能指定快照。每次调用按当前设置重新生成，单次执行使用该次快照。导入的旧包若不支持内部权限协议则受阻，不静默回退。

内部步骤分别检查environment.probe、pptx.validate、assets.crop、ops.component、pptx.build、pptx.inspect、office.render、compare.deck/compare.page、delivery.verify。经验检索被禁用时不附检索结果。未迁移的Office编辑/导出仍为CLI工具，并关联项目、任务和调用证据。

这是受管入口约束，不是操作系统沙箱。相同本地用户直接执行脚本、改数据库、注入进程或制造文件系统竞态不属于本层安全隔离承诺。没有用户新授权，Agent不得改变真实管理开关、信任、目录或宿主配置。

## 状态与恢复

command_status单独说明调用结果，workflow_status保留原控制器状态。等待看图、素材、Office或返修不自动成为成功交付。权限拒绝为permission_denied，无效参数为invalid_arguments，程序错误为failed。子进程超时为outcome_unknown。

超时不自动重试，不强制结束PowerPoint。先调用status并检查受控输出、writer.lock和任务拥有的Office文档。进程已结束且工作流无锁/无未结束operation时，只追加reconciled观察，不能补记原操作成功。有残留锁时，核对无写者后显式使用原受管unlock；需要retry时仍需明确的恢复操作。RPC ID不承担任务幂等职责。

## 证据

继续使用原SQLite events表。记录started、authorized、launched、finished或timeout/unresolved/reconciled，关联call_id、来源、工具、项目、任务、实际HEAD与代码哈希、前后revision、时间和状态。

公开事件只保留参数字段名及数量，不复制result、reason正文、token、异常输入或图片。完整stdout、stderr与代码清单位于独立管理目录的runs/call_id，属于受控证据，协议响应可能含token。不得将这些文件当作公开日志发布。

代码存在和测试通过不证明看图质量。第一阶段开发与分层验收见 `docs/upgrade/phase-01/`，任何未完成层都必须保留not_run/blocked。
