# 第二阶段最小操演

运行 `python examples/phase2/run_demo.py --project <全新目录>`。

程序创建一张明确标记为功能样例的简单参考图，提交已知的两个区域，停在source_review。它不伪造来源审查、Office导出、看图或编辑验收。

接下来让当前Agent打开next_task中的实际参考图、检查内容，然后按当前任务继续。字体与Pillow测试参考不同，样例用于验证流程、局部任务和ID/坐标处理，不用于评估高保真效果。

真实生图需要宿主能力。没有Windows Office时，后续会停在awaiting_office；这属于预期状态，不能修改收据伪装为通过。
