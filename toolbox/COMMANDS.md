# 常用命令

下表列出核心命令语法。受管模式先读取 `manager.py context`，通过 `manager.py describe --tool <ID>` 获取 `managed_argv_prefix`。主流程映射到 `workflow.<命令>`，直接工具使用注册 ID。保留返回的解释器及管理数据目录，不从核心示例绕过停用设置。

```text
python manager.py describe --tool workflow.next
python manager.py execute --tool workflow.next -- --project "<project>"
python manager.py execute --tool ops.component -- --spec examples/phase3/semicircle.spec.json --outdir "<new-output>"
python manager.py execute --tool office.edit-readback -- describe
```

上例适用于默认管理数据目录。独立核心模式从实际 Skill 目录调用 `python toolbox.py`。`--help` 会列出实际参数。

| 命令 | 参数 | 用途 |
|---|---|---|
| doctor | [--out JSON] | 检查本地包/路径，不安装 |
| start | --project NEW --references IMAGE... [--ratio 16:9 --office] | 持久化原图并建立状态 |
| start | --project NEW --scene JSON [--candidate PPTX --office] | 接收已分析scene/外部PPTX |
| next | --project DIR | 自动推进已就绪步骤并返回一个任务 |
| submit | --project DIR --response JSON | 校验当前任务并原子提交 |
| status / handoff | --project DIR | 读取状态与交接摘要 |
| advance | --project DIR [--office] | 只推进确定性步骤，不越过活跃任务 |
| asset-add | --project DIR --file FILE --provenance TEXT | 持久化素材并刷新当前任务 |
| revise | --project DIR --slide ID [--region ID] --reason TEXT | 重开指定区域/页，旧版本保留 |
| replace-scene | --project DIR --scene JSON --reason TEXT | 明确修改完整scene，重新核对来源 |
| replace-candidate | --project DIR --pptx FILE --reason TEXT | 同scene下导入新候选，不从Python覆盖 |
| review-again | --project DIR --task ID --reason TEXT | 补审现有候选，保留旧审查记录 |
| retry | --project DIR --reason TEXT | 恢复失败或中断的程序步骤 |
| unlock | --project DIR --token TOKEN --confirmed-no-active-writer | 人工确认后的遗留锁恢复 |
| finish | --project DIR | 重新核验证据，发布不覆盖的交付副本 |
| workflow.probe/patch/compare/adopt（仅受管） | --project DIR --request JSON | JSON不含project，结构与MCP相同，见[局部合同](../references/local-rebuild.md) |
| tools list/show/run/check | 见--help | 查找代码、模块和手册 |

`tools check` 检查注册文件与手册路径。`tools check --cli` 另运行已注册 Python 入口的帮助命令，核对注册参数和本页、主 Skill、工具索引代码块中的 Python 示例。此检查只传固定子命令与 `--help`，不运行示例中的制图参数。PowerShell 参数、Office 行为和人工操作说明仍需各自验证。

## 直接使用已有脚本

```text
python toolbox.py tools run assets.crop -- source.png crop.png --box 10 20 300 240
python toolbox.py tools run assets.chroma -- generated.png transparent.png --key FF00FF
python toolbox.py tools run assets.trim -- transparent.png trimmed.png --padding 6
python toolbox.py tools run assets.matte -- trimmed.png matte.png --background EEF4F9
python toolbox.py tools run office.smoke -- -OutputPptx "D:/test/native-smoke.pptx"
python toolbox.py tools run office.render -- -Pptx "D:/test/native-smoke.pptx" -OutputDir "D:/test/new-office-export"
python toolbox.py tools run pptx.editing-structure -- --pptx current.pptx --out new-structure.json
python toolbox.py tools run office.group-roundtrip -- --pptx current.pptx --outdir new-group-test --slide 1 --name card_group
```

Direct脚本不自动变更控制器状态。把其真实产物通过当前任务提交，不能运行外部脚本后手改state/哈希。COM模块函数则需要一份创建Slide并导入模块的PowerShell脚本，不支持把Slide对象写成普通字符串参数。

## v1.3直接操作与评测

```text
python toolbox.py ops --help
python toolbox.py ops components
python toolbox.py ops describe flat_semicircle
python toolbox.py ops component --spec examples/phase3/semicircle.spec.json --outdir work/component-new
python toolbox.py ops boolean --spec examples/phase3/boolean.spec.json --outdir work/boolean-new
python toolbox.py ops fonts
python toolbox.py ops font-sheet --spec examples/phase3/fonts.spec.json --outdir work/font-new
python toolbox.py bench --help
python toolbox.py bench plan --suite benchmarks/synthetic-micro/suite.json --config models.actual.json
```

其余任务级命令及完整参数见[直接操作](../references/direct-operations.md)和[评测协议](../references/cross-model-evaluation.md)。下表从真实注册表生成，不能把host/manual当本地可执行脚本。

| 注册ID | 命令/作用 | 入口 |
|---|---|---|
| `ops.components` | 参数化原生组件清单 | `scripts/direct_ops.py` |
| `ops.describe` | 组件参数与示例 | `scripts/direct_ops.py` |
| `ops.component` | 构建原生组件小样与片段 | `scripts/direct_ops.py` |
| `ops.boolean` | 布尔拼接裁切（原生复合路径） | `scripts/direct_ops.py` |
| `ops.asset-layout` | 透明素材主体定位与三底色检查 | `scripts/direct_ops.py` |
| `ops.font-sheet` | 原生字体候选样张 | `scripts/direct_ops.py` |
| `ops.font-evaluate` | Office字形边界与局部对照 | `scripts/direct_ops.py` |
| `ops.patch-scene` | 按允许对象修改scene | `scripts/direct_ops.py` |
| `ops.patch-pptx` | 保留其他部件的PPTX定点修改 | `scripts/direct_ops.py` |
| `ops.regression` | 局部返修区域外像素回归 | `scripts/direct_ops.py` |
| `ops.generation-prepare` | 为宿主生成实际生图任务 | `scripts/direct_ops.py` |
| `ops.generation-ingest` | 接收真实PNG与来源记录 | `scripts/direct_ops.py` |
| `bench.make-suite` | 创建合成跨模型测试集 | `scripts/benchmark.py` |
| `bench.plan` | 核对多模型配置、权限和调用上限 | `scripts/benchmark.py` |
| `bench.run` | 真实多模型API微任务评测（需授权） | `scripts/benchmark.py` |
| `bench.export` | 导出不含答案的宿主测试任务 | `scripts/benchmark.py` |
| `bench.replay` | 离线评分器演练，不算模型实测 | `scripts/benchmark.py` |
| `bench.report` | 分轨道重复测试统计 | `scripts/benchmark.py` |
| `bench.workflow-record` | 完整工具箱工作流证据收集 | `scripts/benchmark.py` |
| `office.inspect-recursive-text` | 递归读取组内、单元格和旋转文字边界 | `scripts/inspect_text_powerpoint.ps1` |
| `ops.fonts` | 列出本机字体名称，不分发字体文件 | `scripts/direct_ops.py` |
| `bench.workflow-report` | 汇总完整工作流记录（不混入微任务得分） | `scripts/benchmark.py` |

| `bench.deterministic` | 等价输入重复构建；零模型调用 | `scripts/benchmark.py` |

## 核心 v1.3.1 实测衔接修复

受管服务动态注册 `workflow.calibrate_plan`、`workflow.calibrate_step`、`workflow.calibrate_report`，MCP对应 `rebuild_calibrate_*`。CLI统一使用 `--project <authorized-project> --request <authorized-json>`，无直接自由参数命令。完整schema由contracts.py生成，见[有界校准](../references/calibration.md)。不计入静态80工具项。

- `python toolbox.py preview --project <project>`：候选已建立后运行真实LibreOffice预审，next发出全页和局部查看任务。
- `python toolbox.py preview --project <project> --receipt <preview-render.json>`：导入已按新协议生成的预审证据；不等价于Office。
- `python toolbox.py tools show regions.normalize`：两种旧局部区域格式的共同入口。
- `python toolbox.py tools show preview.render` 与 `preview.compare`：对既有PPTX单独预览，不覆盖重建。

状态、真实依赖与完整示例见[预审与参数衔接](../references/preview-and-handoffs.md)。


## 经验查询与完整性检查

学习具体制作、编写指令或安排调用顺序时，先看[制作过程与指令模板](../references/production-process-learning.md)。其中的字体、素材、图标和局部返修流程解释每次调用的目的与前置输入；按当前任务填写模板后，再用describe取得真实参数。查询成功与制作方法验证分别记录。

先读取当前context，并用describe取得相应ID的受管参数前缀。以下为核心参数参考，日常调用仍保留当前管理器的执行开关。

```text
python toolbox.py tools run experience.search -- "Office 导出 路径"
python toolbox.py tools run experience.show -- EXP-126
python toolbox.py tools run experience.source -- S05 --start 65 --end 76
python toolbox.py tools run experience.audit -- --details
```

show返回相关工具的实际类型、输入与限制；source核对来源哈希后最多读取80行。audit检查引用与工具路径，不运行Office，也不判断语义提炼完整。完整说明见[经验与工具索引](../references/experience-library.md)。
