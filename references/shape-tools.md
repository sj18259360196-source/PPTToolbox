# 异形构建与操作证据

先用 toolbox_context 与 graphics_inspect 读取当前合同。项目先绑定，rebuild 调用携带当前 context_id。下面四个 graphics 入口由受管服务动态注册，实际写入仍受项目授权、执行开关和工具禁用设置约束。

| 入口 | 用法与输出 | 范围 |
| --- | --- | --- |
| graphics_construct | rounded_polygon 输入 points、corner_inset、canvas、style；radial_repeat 输入 commands、center、count，可选 step_deg。返回 graphics-recipe/1 与原生对象 | 圆角采用退让距离构造三次曲线，不承诺精确圆弧半径。重复点、自交、极短边和过大退让距离拒绝；凹角可用零退让保留尖角 |
| graphics_compare_contours | 输入同尺度 reference、candidate、reference_mask、candidate_mask，可附 exclude_mask，均为 PNG base64。返回叠图、原始对称边界距离、质心位移估计、位移后的辅助结果和未匹配面积 | 掩膜必须是明确的 0/255 二值图，最多一百万像素。位置补偿结果不能覆盖原始误差。掩膜归属由调用者核对，不输出通过分数 |
| graphics_read_properties | 输入 project、项目内 pptx 相对路径、pptx_sha256、targets 中的 slide 与 id。在 assets/native-readback 独立副本保存重开 | 读回填充、渐变色标 alpha、父组、子对象及自由形状节点。混合或不支持属性标为 unknown。源哈希必须不变，读回不代表编辑测试或视觉验收 |
| graphics_boolean_trials | 输入 project、slide、region、有序 inputs、prefix、reason，可选 actions。返回独立 rebuild_patch 请求 | 第一操作数即 primary 与样式来源。仅预检和生成请求，不执行、不自动采用、不增加预算。请求补当前 context_id 后逐项执行 |

布尔操作继续使用 native.topology 的 union、combine、intersect、subtract、fragment。操作数须为顶层、未旋转、连续层序、闭合无文字的纯色不透明对象。需要练习布尔时建立独立操作数，不能去除现有渐变或透明度来满足限制。每种运算从同一基线创建副本；反转 subtract 的输入检查次序。两圆 intersect 应只剩透镜，fragment 的三个部分合起来应覆盖 union。检查保护对象、材质、层序和实际 Office 渲染后，才决定是否 adopt。

节点修改使用 rebuild_patch 的 native.nodes，沿用区域授权、基线 scene/PPTX 哈希、试制与 compare/adopt。每个 edit 给 command_index、point_index、expected 和 delta；max_displacement 使用 scene 坐标单位。M/L 的 point_index 为 0，C 的 0、1 是控制点，2 是终点。索引从零开始，最多 32 次点修改。

只支持闭合 M/L/C/Z 路径。固定原路径坐标框，控制点不能离开；拒绝旋转、翻转及缩放组。未变换组内路径可以编辑。修改不能改变环数、孔洞数、嵌套或绕向，也不能触碰范围外对象。node-readback.json 比较真实 Office 保存结果与独立重建的路径；COM 节点与材质另见 readback.json。它验证文件修改后的读回，不声称执行过鼠标拖动。

完成后执行 rebuild_compare 并查看新渲染。原参考、候选、局部叠图和范围外变化分别核对。圆角草稿、轮廓指标、属性读回及 scene 一致性都不自动提交视觉通过。
