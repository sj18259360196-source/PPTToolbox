# 原生能力库

专项实现仍为 partial。操作卡中的 `callable` 说明代码与必要工具开关，
不代表本机已验证，更不代表视觉通过。按 `office`、`coverage` 和具体证据判断。

## 本机 Union 补验

2026-09-27 的 `stability-r03` 已验证一个限定案例。原项目的两个重叠矩形经
Office Union 形成原生路径，保存重开后可在独立检查副本中改色，其他31个对象
未变，原色 scene 的独立导出为0像素差，并通过原 compare/adopt。
另外四种布尔、孔洞和曲线输入仍未通过本轮实测。

原三次失败分别停在保护内容归一化、被消耗对象的审查引用、结果路径空文本框
属性复现。已有 `native_path_frame` 修复在第四次实际执行中通过。本轮没有
调整 COM 签名，也没有用其他几何引擎替代 Office。

路径结果仍不能使用普通 `fill.set`。本例通过受管 `office.edit-readback`
的 `shape.fill` 验证检查副本，正式候选保留原色。查询 `native.boolean.union`
可取得追加的本机证据。环境只记录 Office16.0，检索仍返回 `needs_review`，
不能把本机功能案例提升为任意环境已验证。第四次授权已经用完，不再重试。

高级条幅 `native-folded-banner-v2/6b9c7ddc83a14d8e7dd64a30` 的依赖仍匹配。
本轮没有新参考交付，也没有增加成功任务数。原 A 账本64/80、保留12张，当前
可支用4张；新参考完整链路预估至少7张，先解决保留额度的使用授权再启动。

## 找操作

现有 MCP 入口保持不变。

```json
{"name":"toolbox_search","arguments":{"query":"文字本身渐变，不是文本框底色"}}
```

搜索返回 `native.text.fill` 后，按需读取操作卡。

```json
{"name":"toolbox_describe","arguments":{"id":"native.text.fill"}}
{"name":"toolbox_manual","arguments":{"path":"native/text.fill"}}
```

`scripts/native_capabilities.py` 是能力 ID、严格参数、示例和检索别名的共同来源。
生成的 scene schema 由 `scripts/generate_native_schema.py` 同步，测试会检查一致性。
每张原子操作卡的最小例子经过现有 `rebuild_patch` schema 校验。

## 执行

使用当前 `rebuild_patch` 的项目、版本、scene/PPTX哈希、页和区域字段。
`changes` 中使用以下结构；目标必须是当前授权区域内的真实稳定名称。
不要把示例名称当作已经存在的对象。

```json
{
  "op": "native.format",
  "id": "slide-001.body.target",
  "format": {
    "version": "1",
    "shadow": {
      "enabled": true,
      "color": "203344",
      "alpha": 0.4,
      "blur_pt": 4,
      "dx_pt": 3,
      "dy_pt": 5
    }
  }
}
```

输出进入原 trial，不自动修改主版本。继续执行原 compare、看图和 adopt。
候选会保存、关闭、重新打开，并与更新 scene 的独立构建检查一致性。
新格式支持矩形、圆角矩形、椭圆及单段单 run 原生文字。混排、旋转、未知效果
或无法保护邻居的效果范围会被拒绝。旧 patch 的限制保持原样。

## 单位与保留规则

坐标仍用原 scene 单位；效果宽度、模糊、偏移和挤出深度用 pt。
色标位置与 alpha 为0至1，alpha表示不透明度。COM transparency等于1减alpha。
DrawingML中1pt为12700EMU，角度1度为60000单位，alpha与色标位置乘100000。

`fill` 和 `shadow` 修改形状；`text_fill`、`text_outline`、`text_shadow`
修改字形。未给出的格式字段保留；显式 `enabled=false`、`mode=none` 或
`warp=textNoShape` 才清除相应效果。不会用重复对象模拟投影或描边。

老的 `Set-PptSolidStyle` 有重置阴影的职责，本专项未改变它。
需要保留阴影时使用受限 `native.format`，不要混用该重置函数。

## 样件与状态

[打开本机实际 Office 样例图册](C:/Dev/PPTToolbox-work/checks/native-capabilities-20260927/atlas/index.html)。
该路径只属于这次本机验证，不是跨机器安装路径。
图册包含实际预览、可编辑样件和操作卡，已在浏览器检查检索与打开行为。
[逐项本机证据矩阵](C:/Dev/PPTToolbox-work/checks/native-capabilities-20260927/capability-matrix-final.json)
与静态代码目录分开，避免把本机样件结论自动推广到其他 Office 环境。

本轮证据位于专项 HANDOFF 指定的外部目录，未放入程序包或旧学习库。
合成已知参数样件、Agent检索记录、盲测与正式交付分别记录。
字体声明与逐字形字体解析分开，后者仍可能是 unknown。
`WarpFormat` 的 COM 读值与保存节点、实际图像存在差异时必须保留差异记录。

原子操作与五个创建配方分开。配方通过既有 components/probe 编译，
不会执行自由脚本。可检索到配方不表示它已经通过隔离学习库启用。
原生 Group、Fragment、Ungroup、SVG转换和文字轮廓化各是不同操作。

现有字体枚举和样张继续使用 `ops.fonts`、`ops.font-sheet`，不安装或分发字体。
现有布尔生成器使用 Shapely 创建原生复合路径；椭圆为显式采样近似。
这不能替代 PowerPoint MergeShapes 的输入消耗、PrimaryShape与实际结果映射验证。
