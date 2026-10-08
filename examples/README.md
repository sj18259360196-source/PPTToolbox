# 三页功能样例

three-page-scene.json是人工构造的技术测试，不对应用户22份记录的原图。
三页依次覆盖普通文字/渐变/透明图、表格/带工作簿图表、连接线/自由曲线/分组。
使用python scripts/build_pptx.py examples/three-page-scene.json <新文件.pptx>构建。
生成的PPTX通过结构与内容检查不等于Office渲染或视觉验收。
所有数据是synthetic，不能当作科研数据。未包含字体文件或外部版权素材。
