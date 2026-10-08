# 实测衔接修复与独立预审

本页说明当前制作工具的参数格式、任务字段和非 Office 预审衔接。内置工具随软件统一更新，版本规则见[版本与更新](../manager_docs/VERSIONS.md)。

## 同一份局部区域文件

`compare.page`、`ops regression`共享以下格式。推荐带名称的记录，旧四整数数组继续兼容。

```json
[
  {"id":"leaf_detail","bbox":[50,160,170,260],"object_ids":["slide-001.intro.leaf"]}
]
```

`bbox`严格为原图像素 `xyxy`，即左、上、右、下。不是scene对象的 `xywh`；不猜测、不自动缩放。不得使用full、comparison、deck-comparison、readme作为区域ID，大小写重复也被拒绝。

多页格式为 `{"slides":[{"index":1,"regions":[...]}]}`。单张图工具读到多个页号时必须明确加 `--slide 1`，不会自动使用第一页。也支持 `{"regions":[...],"coordinate_format":"xyxy","units":"source_pixels"}`。

```text
python toolbox.py tools run compare.page -- reference.png render.png --regions regions.json --outdir compare-new
python toolbox.py ops regression --before before.png --after after.png --regions regions.json --outdir regression-new --environment-before same-actual-environment --environment-after same-actual-environment
python toolbox.py tools run regions.normalize -- --spec regions.json --size 1672 941 --output canonical-regions.json
```

`environment-*`应填写实际记录的渲染环境，不能为了通过而编写相同字符串。程序只判断调用者提供的身份是否一致，不能自动证明环境相同。

## 当前任务先提供约束和示例

page_plan的next结果直接带 `submission_constraints`，列出角色枚举、保留ID、坐标格式和真实尺寸。region_objects另有 `response.examples.json`，包含图片对象的 `asset_role`、`source_kind`、实际素材路径取得方式和生成请求格式。

示例单独保存，不会把假路径或默认图片自动插入PPT。角色必须按对象决定。程序补坐标换算、稳定ID、editability；不擅自猜图标是照片还是装饰。

区域响应可记录 `asset_decisions`。每项包含 `target_id、route、generation_considered、reason、remaining_risk`；route为native、crop、user_asset、external或generated。target_id是本区域实际对象/组件的短ID。记录随区域提交保存，并进入source_review；兼容旧响应，没有记录不能被当作已经比较过生成方案。

一旦裁切有残字、修补明显、图标轮廓不符，不能只依据文件存在就采用。对于已获准近似、内部无需逐路径编辑的局部，直接提交packet中的 `request_asset`；无需先做两轮失败试验。实际生成仍由宿主工具执行。

## 缺少Office时继续正式组织预审

先完成分析和source_review，让next生成候选文件。状态到awaiting_office后，可以执行：

```text
python toolbox.py preview --project <project>
python toolbox.py next --project <project>
python toolbox.py submit --project <project> --response <当前响应文件>
```

preview只调用本机实际LibreOffice及PyMuPDF。可用 `--executable` 指定已安装的LibreOffice；不安装软件、不下载模型、不向外部发送参考图。预审不是必需依赖，Windows Office正常路径无需安装这两项。

它创建隔离的LibreOffice配置和候选副本，输出PNG，然后自动生成全页和必查局部的左右图、叠加图、差异图。每张左右图右侧明确写 `LIBREOFFICE PREVIEW / Office未验证`。

新任务依次为preview_full和preview_local，必须实际打开返回的图片，不能批量填通过。发现问题返回needs_changes，使用revise或replace-scene/candidate修改；补审同一文件可用review-again。

所有预审完成后恢复awaiting_office。预审记录保存在run.preview，正式run.render、run.comparison和run.reviews不会因此被填入。finish仍要求真实Office收据、正式对照和新一轮正式审查；预审结果不自动转为最终通过。

已经在其他授权机器准备预审收据时，可用 `preview --project <project> --receipt <preview-render.json>` 导入；程序检查实际PPTX、scene和每页PNG身份，但不会独立证明远程执行。

## 单独为既有PPTX预览

```text
python toolbox.py tools run preview.render -- --pptx candidate.pptx --scene scene.json --outdir preview-render-new
python toolbox.py tools run preview.compare -- --pptx candidate.pptx --scene scene.json --render preview-render-new/preview-render.json --regions regions.json --outdir preview-comparison-new
```

这两个入口不重建或覆盖现有PPTX。输入需配套原图和scene；文件关联检查不等于scene完整、业务数据准确或模型已看懂。

## 失败与续作

预审失败时不撤销当前Office任务、不覆盖上次证据，补齐缺失条件后重试preview。成功切到预审后旧Office任务token作废，必须使用next返回的新任务。输入版本改变时旧预审失效并保存在旧run中。

已取得当前实际Office导出时不再建立替代预审，直接使用正式对照。预审收据即使把renderer文字改成Microsoft PowerPoint，也会因预审格式标记被Office验证器拒绝；这防止误用，不是对恶意伪造执行记录的数字签名认证。
