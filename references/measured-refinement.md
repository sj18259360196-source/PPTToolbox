# 原图校准与冻结后的复现检查

用于文字位置看似对齐却仍不贴合原稿、复杂装饰被过度简化，以及冻结资产后裁切失效的返修。实际案例与验证边界见研究背景校准案例（本地验收记录未随包提供）。

## 先把差异落实到对象

同时看整页和关键局部，记录字形实际边界、轮廓、箭头端点、颜色过渡及遮挡。文本框坐标相同不代表字形相同。调整字号会改变文本框内部的垂直位置，需重新检查。允许装饰近似也不能直接放过可以修正的漏项。

像素差用于同一原稿、相同渲染尺寸下比较候选。大面积留白会稀释局部错误，不把平均像素差转换成还原百分比。

## 原生图片裁切

scene 图片可声明 `source_crop`，单位为原始位图像素，顺序为 x、y、宽、高。`bbox` 表示幻灯片内显示范围，两者独立。明确使用 `fit=stretch`，避免与 contain、cover 二次裁切混用。

```json
{
  "id": "s1.decorative_badge",
  "kind": "image",
  "bbox": [100, 100, 140, 140],
  "asset": "assets/reference.png",
  "source_crop": [149, 302, 140, 141],
  "fit": "stretch",
  "mask": {"geometry": "ellipse"},
  "asset_role": "decoration",
  "source_kind": "crop",
  "editability": "image_replace",
  "evidence": {"status": "observed", "note": "Only a text-free decorative badge is visible"}
}
```

构建器检查裁切是否超出图片尺寸，直接写入原生图片裁切。导入流程改资产文件名后，这些参数仍随对象保留。不要在外部后处理里靠冻结前的文件名猜对象。

先检查裁切可见区域中的正文、单位、边框和邻近元素。普通文字与信息关系继续原生。该方法保留源图片作为图片底层数据，裁切外内容并未从文件删除；它不能用于隐私脱敏。图片仅支持整体和裁切编辑，不代表内部像素或路径可编辑。

## 连续光晕

需要原生渐变光晕时，可使用径向渐变，边缘透明、中心渐显。`stops` 的0位于焦点、1位于边缘；`center` 为形状内部的归一化焦点坐标。默认仍为线性渐变，旧场景无需修改。

```json
{"type":"radial","center":[0.65,0.3],"stops":[
  {"position":0,"color":"FFFFFF","alpha":0.45},
  {"position":1,"color":"FFFFFF","alpha":0}
]}
```

多加色标不一定更接近原稿，过近的色标可能形成可见分界。用 PowerPoint 导出判断高光位置和过渡，不能仅凭 XML 声明接受效果。

## 分阶段验证编辑

整组移动使用 `office.group-roundtrip`。只验证移动与恢复，期间不再改变裁切、宽高或文字内容。裁切会改变图片边界，混在同一几何断言里会产生误报。

图片裁切使用已有的 `office.edit-readback`，在另一份副本中操作。

```json
[{"op":"picture.crop","slide":1,"name":"s1.decorative_badge","edge":"left","points":113.25}]
```

`points` 为 PowerPoint CropLeft/Top/Right/Bottom 的绝对点值，不能填 scene 的源图像素坐标。先读取当前值，再提交不同的新值。保存重开使用0.05pt数值容差，仍需打开导出图检查边缘和遮挡。它不验证重新替换图片、全部对象或任意长文排版。

## 把三种结论分开

经管理器发现并调用 `pptx.rebuild-diff`。

```text
--left candidate.pptx --right rebuilt.pptx --left-render candidate.png --right-render rebuilt.png --out new-report.json
```

工具分别报告包文件哈希、`ppt/` 部件内容差异、渲染尺寸及像素差范围。不缩放图片对齐，不替模型判定视觉通过，也不把内部结构相同解释为原图一致。

最终用冻结 scene、资产和保存的脚本重建。绑定同一候选完成整页、局部、编辑、复现与交付。失败候选保留拒绝记录；任务提交枚举使用 `needs_changes`，不要写不支持的 `failed`。
