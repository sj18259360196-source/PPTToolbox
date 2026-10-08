# 原生操作功能样例

```text
python examples/phase3/run_demo.py --outdir work/phase3-demo-v001
```

在新目录建立三页原生组件PPTX、字体样张、主体定位检查图、scene补丁例子与结构检查。原图和数值均为本地代码产生的合成数据，不是用户原稿复刻。没有自动通过视觉审查，不调用生图、不结束Office。

实际Windows先检查字体候选，再导出native-specimens.pptx和字体样张。用户需要内部路径编辑的图标不可直接替换为位图；本例图标明确为可替换图片。缺可选Shapely时第三栏明确替换成内置环带，不把这次示例记录成布尔操作成功。

[随包预览](preview-001.png)使用LibreOffice生成，仅供理解组件，不能作为PowerPoint验收依据。

随包还有[原生示例PPTX](native-specimens.pptx)、[冻结scene](specimen.scene.json)、[第2页](preview-002.png)、[第3页](preview-003.png)和[字体样张预览](font-preview.png)。字体预览也是LibreOffice结果，不代表本机安装了候选字体或Office已经验证。
