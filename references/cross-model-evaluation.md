# 第四阶段评测协议

v1.3.0包含可运行评测工具，严格区分执行程序测试、真实API微任务、完整宿主工作流。构建了评测框架，不代表已经证明跨模型稳定。当前发布没有真实模型API或Windows Office测试结果。

## 1. 三条独立记录

| 轨道 | 输入 | 能验证 | 不能证明 |
|---|---|---|---|
| offline_replay / transport_fixture | 手写响应、模拟HTTP或测试收据 | 判题、预算、失败计数、流程拒绝错误的行为 | 有模型实际运行、模型质量、Office视觉 |
| live_api_microtasks | 实际多模态API与固定合成图片 | 组件选择、文字转录、路线选择、缺陷辨认等限定任务 | 完整PPT复刻、宿主工具使用、生图或用户验收 |
| host_workflow_import | 模型在宿主实际执行完整toolbox项目 | 完整证据链、完成/阻塞、任务数与版本数 | 模型身份认证或仅凭收据证明视觉正确 |

任何轨道不改名充当另一轨道。接口错误、未完成输出、JSON失败、漏任务都不能从分母删除。通过率是特定微任务指标，不命名为还原率。

## 2. 合成测试集

包内[synthetic-micro/suite.json](../benchmarks/synthetic-micro/suite.json)包含8项独立绘制案例：半圆、分区环带、双向箭头、混排单位、复杂局部PNG选择、漏箭头审查、无错误负对照、原生椭圆照片窗。图片由本地绘图代码产生，没有调用生图，没有借用私有原稿。

这是窄范围、引导式工具使用测试。评分标准要求选指定组件名称、保留原文字段和近似几何，不接受所有可能的等价实现；不能据此评价模型通用能力。几何容差明确记录在代码和逐项结果中。用于审查的无错误负对照会统计误报。

suite中的expected只供本地判题。API请求去掉expected，病例ID变为不带答案名称的标识。宿主测试请只发送export产生的公开任务，不让执行模型同时读取判题代码或suite答案。整个包不是防作弊隔离沙箱。

可重新生成新测试集：

```text
python toolbox.py bench make-suite --outdir work/synthetic-suite-v001
```

字体或生成环境变化可能改变图片，因此真实对比应复用冻结后的同一suite和图片哈希，不要为每个模型重新生成。

## 3. 先隔离执行链变量

```text
python toolbox.py bench deterministic --scene frozen-project/scene.json --repetitions 3 --outdir work/deterministic-v001
```

在新目录复制依赖，以不同JSON空白、对象键顺序和Unicode转义重复构建同一语义。比较原生XML规范化结果、媒体与嵌入工作簿内容，忽略docProps元数据，不要求整个PPTX每字节相同。这个结果仅证明所测输入下执行代码一致，模型调用为零，不验证看图、Office显示或模型质量。

## 4. 真实模型API测试

复制[models.example.json](../benchmarks/models.example.json)，填写当前真实模型ID与已经获准的base_url。key只通过指定环境变量提供，不写入JSON或提示词。默认不会联网、安装依赖或花费额度。

```text
python toolbox.py bench plan --suite benchmarks/synthetic-micro/suite.json --config models.actual.json
```

plan检查参数和预算，不发送请求。示例为2个模型×8项×3轮，共48个trial；max_repair_attempts为0时最多48次调用。令牌上限不是金额估算。只有用户授权所选端点、图片上传和调用预算后运行：

```text
python toolbox.py bench run --suite benchmarks/synthetic-micro/suite.json --config models.actual.json --outdir work/live-run-v001 --allow-network --approve-upload
```

支持明确配置的Responses与Chat Completions协议，未宣称兼容所有第三方服务。Responses使用max_output_tokens；Chat默认max_completion_tokens，可显式选择服务要求的max_tokens。不设置臆测的模型默认temperature、seed或reasoning参数；不支持的配置会被服务拒绝并计入失败。HTTPS必需，只有显式批准的loopback允许无认证HTTP。拒绝重定向，避免把凭据发到未批准端点。

schedule_seed只固定模型/案例/轮次的混合执行顺序，不保证模型输出确定。记录配置快照、实际请求模型、接口报告模型、响应ID、延迟、usage、原始响应及各次失败。修复次数0—2只提供通用JSON/结构提示，不把答案反馈给模型；语义判题失败不会被暗中重试。

```text
python toolbox.py bench report --runs work/live-run-v001/run.json --out work/live-summary-v001.json
```

报告保留每轮通过比例、最小/最大、总体波动、错误数、无错误样例误报。描述性Wilson区间基于相关的有限案例，不代表总体保证。至少两个不同的接口报告模型、每组3轮、同套输入、相同覆盖和执行环境，才登记存在重复跨模型微任务测量；这仍不是完整工作流稳定结论。不同模型、采样设置、端点、参数预算需结合configuration.json解释，不能只拿一个总分排序。

## 5. 没有API时导出宿主任务

```text
python toolbox.py bench export --suite benchmarks/synthetic-micro/suite.json --outdir work/public-packets-v001
```

公开packet引用冻结的本地图片，需让宿主真实查看。它不自动切换Codex模型、不控制宿主设置，也不伪造模型身份。

```text
python toolbox.py bench replay --suite benchmarks/synthetic-micro/suite.json --responses authored-responses.json --outdir work/offline-replay-v001
```

replay只能称作离线判题回放；需要覆盖全部案例，失败也以null保留。即使内容来自真实模型，若没有可靠调用证据，该命令也不会替它升级为真实API记录。

## 6. 完整工作流测试

每个模型、每次重复使用新的项目目录，使用同一Skill包、原图、字体、Office版本、工具权限和素材。先用固定素材隔离生图差异，再单独测试真实生成路线。模型从start→next→submit执行，不发预填写的通过记录，不混用其他模型生成的scene。

在用户实际宿主中执行完成或受阻后，填写[host-run.metadata.json](../benchmarks/host-run.metadata.json)，保存日志、实际工具调用与使用的模型设置。

```text
python toolbox.py bench workflow-record --project actual-project --metadata actual-host-metadata.json --outdir work/workflow-record-v001
python toolbox.py bench workflow-report --records work/workflow-record-v001/workflow-record.json work/workflow-record-v002/workflow-record.json --out work/workflow-summary.json
```

collector只读项目，重新检查已存在的完整证据链，不补填任何审查，不将等待视为通过。记录模型身份为host-asserted，execution_kind必须如实区分真实与合成。汇总按原图集合、Skill版本、请求模型和执行类型分组，同时保留未完成任务。不得将已有完整收据的数量直接叫视觉成功率。

完整工作流还需独立检查关键文字/关系漏错、图形相似性、编辑能力、区域外误改、无效重试和人工介入。当前collector只实现证据可用性和任务/版本计数，不自动评价这些语义指标，也没有能独立启动所有模型宿主的通用适配器。

## 7. 公平性与可解释性

固定题目与输入身份，保留失败，不只看平均值。比较最差轮次和关键错误，勿靠一律blocked换低错误率。使用8项熟悉题只做冒烟检查；正式研究另加未参与组件开发的页面，并对独立视觉评审给出明确标准。

换模型续作是另一类任务，不能与从零复刻混合。为它保留同一个冻结项目检查点，各模型从副本继续，检查旧任务拒绝、状态恢复、已确认内容保留。程序回归已经覆盖状态机制，真实模型在这些任务上的表现本次未实测。

## 8. 资料依据与边界

原始经验提出文本/关系与视觉分开核对、关键局部早审、真实渲染和版本一致性；本评测工具是新增工程，不能回写成22份历史任务已经开展跨模型实验。外部协议依据见[官方资料](official-sources.md)的D29—D33。没有API凭据或Office时，应明确写not_run/blocked，照常交付已经验证的代码与待执行测试计划。
