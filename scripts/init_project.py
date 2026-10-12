"""Create a persistent, empty analysis project. Does not infer page objects."""
from __future__ import annotations
import argparse, shutil, sys
from pathlib import Path
from PIL import Image
from common import sha256,write_json

def initialize(output:Path,inputs:list[Path],ratio:str|None=None):
    if output.exists():raise FileExistsError('Use a new project folder; existing project is never overwritten')
    if not inputs:raise ValueError('At least one actual reference image is needed')
    metadata=[]
    for p in inputs:
        with Image.open(p) as im:metadata.append((p,im.width,im.height))
    w=metadata[0][1];h=metadata[0][2]
    if ratio:
        a,b=map(float,ratio.split(':'))
        if a<=0 or b<=0:raise ValueError('Ratio must be positive')
        h=w*b/a
    output.mkdir(parents=True)
    for sub in ['input','assets','build','evidence','delivery']:(output/sub).mkdir()
    slides=[];refs=[]
    for i,(p,iw,ih) in enumerate(metadata,1):
        rel=f'input/slide-{i:03}{p.suffix.lower()}';shutil.copyfile(p,output/rel)
        slides.append({'id':f'slide-{i:03}','reference':rel,'reference_mapping':'TO_BE_ANALYZED: original pixels to common logical canvas; do not assume the same scale for every input image','objects':[]})
        refs.append({'slide':i,'path':rel,'size':[iw,ih],'sha256':sha256(output/rel)})
    scene={'version':'1.0','title':'Reference rebuild','canvas':{'width':w,'height':h,'width_pt':960,'height_pt':960*h/w,'mapping':'uniform','background':'FFFFFF'},'slides':slides}
    write_json(output/'scene.json',scene);write_json(output/'input/references.json',refs);write_json(output/'evidence/review-regions.json',{'slides':[{'index':i,'regions':[]} for i in range(1,len(slides)+1)]})
    (output/'TASK.md').write_text('''# 制作任务\n\n先查看 input 中的全部参考图，确认整页背景、分区、层级和各组件编辑要求。\n先读取当前 production_settings。页面独立文字保持原生，照片按用户保真要求决定保留或参考生成，准确身份和明确原件保留约束继续有效。已有素材按来源资格与编辑要求选路，素材内部文字保留原文。图片生成优先时，复杂插画与装饰标题可直接参考生成独立素材；可编辑绘制优先时，使用真实原生形状或路径并保留内部编辑。simple_icon 简单图标在两种模式下都原生绘制，简单插画按模式与轮廓选路，几何图形按完整部件原生制作。字体匹配与段落或逐行组织按当前设置执行。\nscene.json 是空白分析模板，validate_scene 在对象为空时会拒绝构建。\n参考图尺寸已读取，逻辑画布比例仍需按用户要求确认并统一映射。\n整页截图不得代替整页组件重建。\n''',encoding='utf-8')
    return scene

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project',required=True,type=Path);ap.add_argument('--ratio');ap.add_argument('references',nargs='+',type=Path)
    a=ap.parse_args()
    try:initialize(a.project,a.references,a.ratio);print(f'Created {a.project}; Agent analysis is the next required step')
    except Exception as exc:print(str(exc),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
