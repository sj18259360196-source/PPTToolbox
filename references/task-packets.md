# 局部任务包与提交

主入口只需next与submit。packet中有kind、target、context、required_view_files、相关手册、建议工具和输入身份；响应模板只需要填写result。task_id/token由程序写入，不能更改。

## page_plan

查看整页。按背景到前景列少量区域，不为追求表面覆盖把整个页面拆成几十个像素块。每区包含id、bbox、role、summary；复杂区域标local_review。

```json
{"regions":[{"id":"header","bbox":[0,0,1600,180],"role":"header","summary":"原图标题区","local_review":false},{"id":"diagram","bbox":[40,220,850,850],"role":"diagram","summary":"节点与反馈关系","local_review":true}],"uncertainties":[]}
```

bbox是**原图**xyxy。示例尺寸只解释格式，必须按当前真实图片测量。漏掉的内容不会被程序凭空补全，source_review会要求再次看原图。

## region_objects

该任务只提供当前区域裁图、全页位置、已提交相邻对象ID和可用素材。坐标使用**局部裁图**像素，不必计算PPT单位。

```json
{"objects":[{"id":"label","kind":"text","text":"保留原文","bbox":[20,12,220,36],"style":{"font":"Arial","font_east_asia":"Microsoft YaHei","font_size_pt":20,"color":"123456"}}],"source_notes":"文字和位置依据当前裁图；字体为待渲染候选","relationship_ids":[],"uncertainties":[]}
```

程序补全id前缀与editability；未声明的evidence默认inferred，不能因此声称测量完成。对象类型与style字段沿用scene schema。只接受明确支持的字段；未知形状或高级格式不会被静默改成矩形。

组内对象仍使用该区域局部像素。连接端点指向同区短ID时程序补前缀；跨区关系用packet给出的完整ID。需要先有目标对象，程序不会猜不存在的连接目标。需经常改数据的图仍用chart并保留来源说明。

## 需要宿主生成素材

在region_objects响应中使用以下替代格式。

```json
{"action":"request_asset","request":{"id":"asset-01","purpose":"当前区域复杂全息设备图标，标签另行原生重建","prompt":"按当前参考局部保留主体数量、轮廓、视角和主色；只生成独立设备，不生成文字、数字、卡片或标识；需要真实透明背景","transparent":true,"allowed_approximation":true}}
```

按[素材唯一决策](asset-policy.md)确认范围与权限。控制器暂缓该区域，可继续其他就绪区域，然后发出asset_material任务。PNG生成本身由宿主真正调用。提交file、tool_used、provenance；model_reported没有工具证据时为null。任务要求透明时程序拒绝RGB棋盘格、全不透明或全透明空图。

```json
{"file":"<实际PNG绝对路径>","tool_used":"<实际工具名称>","provenance":"用户参考局部生成；被遮挡区域是近似补全","model_reported":null}
```

得到素材后，下一个区域任务提供内容寻址asset路径。通过assets.chroma/trim/matte处理时输出到新文件；用asset-add持久化新素材，它会更新当前任务token。此阶段不自动保证去白边、主体锚点或与原图同等质感。

## source_review

重新读原图；packet给出当前文字、表格、关系与区域备注。检查截图→转录这一层，不能以PPT与scene一致代替。

```json
{"status":"passed","note":"<实际逐项观察与依据>","reviewer":"<执行者标识>","viewed_files":["<next返回的实际图片路径>"]}
```

status可为passed、needs_changes、blocked。格式示例不是通过模板；只有实际完成对应检查才填passed。

## candidate与office_render

candidate提交真实PPTX文件。office_render提交真实收据路径，程序检查候选哈希、逐页PNG、尺寸与页号后复制，下一次next自动做全页和局部对照。不要把别的渲染器输出改个字段称为Office。

```json
{"file":"<真实候选PPTX>"}
```

```json
{"receipt":"<真实Office输出目录>/office-render.json"}
```

## review_full与review_local

全页检查分别填写visual_full、raster_scope、text_geometry，避免一个总体通过掩盖其中未执行项。实际图像路径必须出现在viewed_files。局部任务需要填写该区域的观察，若涉及关系，逐个填写relationships中的object_id及note。没有适用局部或连接时由程序推导不适用，模型不能用不适用跳过已声明对象。

findings可记录明确问题及拟修改对象。若任何检查需要修改，控制器保留awaiting_revision，调用revise或review-again；不把再生成一张对照视为问题已经修好。

## editable_behavior与reproducibility

按packet列出的类型执行实际修改/重建，actions记录kind和note（可加object_id、slide_id），files指向实际产物。编辑测试PPTX必须与当前候选不同且不得直接改候选；重建输出也要另存。程序检查文件存在、PPTX包可读和基本动作覆盖，不能单靠这些证明所述动作真实发生。

## 提交失败与能力不足

无效字段返回invalid_submission和具体错误，原活跃任务保留，修result后重交。任务id/token旧了返回stale_task，重新next。文件被外部改写会拒绝沿用证据。

没有Office或宿主生图时不提交虚构结果，保留当前任务；可以更换实际具备能力的宿主后继续。同一项目不并发写。要切换已失败素材方案，可revise重开区域并保留原因。
