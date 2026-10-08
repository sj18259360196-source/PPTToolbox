"""Create a controlled two-region demo and stop at source review. No fake Office.
Run: python examples/phase2/run_demo.py --project <NEW absolute directory>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import workflow
from common import read_json,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);a=p.parse_args()
    project=a.project.resolve()
    if project.exists():raise FileExistsError('Use a new demo project')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='ppt-controlled-demo-') as temp:
        reference=Path(temp)/'reference.png';im=Image.new('RGB',(640,360),'white');d=ImageDraw.Draw(im)
        d.rectangle([10,20,300,330],outline='black');d.text((24,38),'LEFT / Editable text',fill='black')
        d.rectangle([340,20,630,330],outline='black');d.text((354,38),'RIGHT / Native shape',fill='black');im.save(reference)
        workflow.start(project,[reference])
    def submit_result(result):
        task=workflow.next_task(project);file=Path(task['task']['response_template']);r=read_json(file);r['result']=result;write_json(file,r);workflow.submit(project,file)
    submit_result({'regions':[{'id':'left','bbox':[0,0,320,360],'role':'content','summary':'Synthetic left block'},
                              {'id':'right','bbox':[320,0,640,360],'role':'content','summary':'Synthetic right block'}]})
    for text,label in [('LEFT / Editable text','left'),('RIGHT / Native shape','right')]:
        submit_result({'objects':[{'id':'card','kind':'shape','geometry':'rect','bbox':[10 if label=='left' else 20,20,290,310],'style':{'line':'000000','line_width_pt':1}},
                                  {'id':'label','kind':'text','text':text,'bbox':[24 if label=='left' else 34,38,260,35],'style':{'font_size_pt':18}}],
                       'source_notes':'Controlled function demo. Font rendering differs from Pillow reference; not a fidelity benchmark.'})
    task=workflow.next_task(project)
    assert task['task']['kind']=='source_review'
    print(json.dumps({'demo_status':'stopped_before_source_review','next_task':task,
       'scope':'Actual start/region submission/coordinate assembly. No source/visual approval, Office receipt, or model generation simulated.'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
