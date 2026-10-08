"""Build independent native specimens and operation examples; never pre-approve reviews.
Run with a new output folder. Synthetic content is not a reconstruction of a user's page.
"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from common import write_json,sha256,staged_directory
from components import compile_component,boolean_component
from build_pptx import build
from inspect_pptx import inspect
from text_ops import font_sheet
from asset_ops import placement_report
from patch_ops import patch_scene
from PIL import Image,ImageDraw

EV={'status':'synthetic','note':'Native toolbox function sample; not real experimental data'}
def text(i,t,x,y,w,h,fs=18,bold=False,color='243F51'):
    return {'id':i,'kind':'text','role':'content','editability':'text','evidence':EV,'bbox':[x,y,w,h],'text':t,'style':{'font':'DejaVu Sans','font_east_asia':'Noto Sans CJK SC','font_size_pt':fs,'color':color,'bold':bold,'margin_pt':0,'wrap':False}}
def box(i,x,y,w,h,fill):
    return {'id':i,'kind':'shape','role':'card','editability':'shape','evidence':EV,'bbox':[x,y,w,h],'geometry':'round_rect','style':{'fill':fill,'line':None}}
def scaffold(title,sub):
    return [text('title',title,44,26,1110,45,26,True),text('subtitle',sub,44,78,1110,32,12,color='536B7B'),text('footer','FUNCTIONAL SPECIMENS  /  synthetic inputs  /  Office rendering still required',44,642,1110,24,10,color='617886')]
def run(outdir):
    with staged_directory(outdir) as stage:
        assets=stage/'assets';assets.mkdir()
        photo=Image.new('RGB',(600,360),'#91BDDA');d=ImageDraw.Draw(photo)
        d.rectangle((0,205,600,360),fill='#719C7C');d.rectangle((90,100,260,250),fill='#E1EAE4');d.rectangle((325,145,510,270),fill='#BECED3');d.ellipse((300,260,570,330),fill='#386B8C');photo.save(assets/'synthetic-photo.png')
        alpha=Image.new('RGBA',(180,180),(0,0,0,0));d=ImageDraw.Draw(alpha);d.ellipse((44,34,140,130),fill='#489CC0');d.line((66,82,86,102,120,60),fill='white',width=8);alpha.save(assets/'synthetic-icon.png')
        canvas={'width':1200,'height':675,'width_pt':900,'height_pt':506.25,'mapping':'uniform','background':'F4F8FA'}
        p1=scaffold('Native geometry recipes','Eight recipes compile to editable shapes, paths, text and pictures.')
        recipes=[('flat_semicircle','Flat-base semicircle',[105,196,160,100],{}),('segmented_ring','Separate ring sectors',[500,194,145,145],{}),('double_arrow','Two-ended wide arrow',[865,201,224,65],{}),('annular_sector','Annular sector',[110,432,155,130],{'sweep_deg':275}),('notched_card','Notched native card',[480,424,205,120],{}),('feedback_curve','Fixed feedback curve',[865,418,224,130],{'bidirectional':True})]
        for j,(recipe,label,b,p) in enumerate(recipes):
            row,col=divmod(j,3);x=44+col*380;y=132+row*242
            p1 += [box('card'+str(j),x,y,352,220,'FFFFFF'),text('label'+str(j),label,x+16,y+14,320,28,15,True)]
            p1.append(compile_component({'id':'component'+str(j),'recipe':recipe,'bbox':b,'params':p,'evidence':EV}))
        p2=scaffold('Composites and native image windows','Holes remain holes. Text stays text. The image is independently replaceable.')
        p2 += [box('left',44,132,352,460,'FFFFFF'),box('mid',424,132,352,460,'FFFFFF'),box('right',804,132,352,460,'FFFFFF')]
        p2.append(text('ll','Native ellipse photo',65,155,306,32,16,True));p2.append(compile_component({'id':'photo1','recipe':'photo_window','bbox':[100,220,240,180],'params':{'asset':'assets/synthetic-photo.png','source_kind':'user','provenance':'Locally drawn synthetic picture'},'evidence':EV}));p2.append(text('lc','Mask is p:pic geometry',65,450,306,44,13))
        p2.append(text('ml','Independent node parts',445,155,306,32,16,True));p2.append(compile_component({'id':'node','recipe':'icon_node','bbox':[480,214,240,240],'params':{'label':'EDITABLE','value':'32.5%','description':'sample only','icon_asset':'assets/synthetic-icon.png','icon_provenance':'Synthetic local icon'},'text_style':{'font':'DejaVu Sans','font_size_pt':15},'evidence':EV}));p2.append(text('mc','Label / value / icon separate',445,490,306,44,12))
        p2.append(text('rl','Boolean subtract',825,155,306,32,16,True))
        try:
            p2.append(boolean_component({'id':'hole','operation':'subtract','operands':[{'geometry':'rect','bbox':[863,220,220,180]},{'geometry':'ellipse','bbox':[918,260,110,100]}],'style':{'fill':'3B84AD','line':None},'evidence':EV}));p2.append(text('rc','Actual reverse-wound hole',825,450,306,44,12))
            optional='Shapely boolean example built'
        except RuntimeError:
            p2.append(compile_component({'id':'hole','recipe':'annular_sector','bbox':[880,210,185,185],'params':{'sweep_deg':360},'evidence':EV}));p2.append(text('rc','Shapely absent: ring fallback',825,450,306,44,12));optional='Optional boolean not run; ring specimen substituted and explicitly recorded'
        p3=scaffold('Native tables and data charts','Synthetic values demonstrate cell formatting, row control, axis settings and editable data.')
        p3 += [box('tc',44,132,460,460,'FFFFFF'),box('cc',534,132,622,460,'FFFFFF'),text('tl','Merged header + unequal rows',64,155,410,32,16,True),text('cl','XY chart + real embedded data',554,155,570,32,16,True)]
        p3.append({'id':'table','kind':'table','role':'table','editability':'table','evidence':EV,'bbox':[65,223,416,276],'rows':[['Synthetic example',''],['Component','Count'],['Ring sectors','4'],['Arrowheads','2']],'column_widths':[285,131],'row_heights':[58,56,84,78],'merges':[[0,0,0,1]],'cell_styles':[{'row':0,'col':0,'style':{'bold':True,'fill':'D5E9F2'}},{'row':2,'col':1,'style':{'bold':True,'color':'25739C'}}],'style':{'font':'DejaVu Sans','font_size_pt':14,'line':'AEC5D3','fill':'FFFFFF','margin_pt':5}})
        p3.append({'id':'chart','kind':'chart','role':'chart','editability':'data_chart','evidence':EV,'bbox':[555,210,577,330],'chart_type':'xy','series':[{'name':'A','points':[[0,1],[1,2],[2,4],[3,3]],'color':'378BAE','marker':'circle','marker_size_pt':6,'line_width_pt':2},{'name':'B','points':[[0,.5],[1,1.4],[2,2],[3,2.7]],'color':'D59A4A','marker':'square','marker_size_pt':5,'line_width_pt':1.8}],'axes':{'x':{'minimum':0,'maximum':3,'major_unit':1,'title':'Sample index','gridlines':False},'y':{'minimum':0,'maximum':5,'major_unit':1,'number_format':'0.0','title':'Synthetic value'}},'legend_position':'top','data_provenance':'All chart values are invented function-test data, not experimental observations.'})
        scene={'version':'1.0','title':'Phase 3 native toolbox specimens','canvas':canvas,'slides':[{'id':'geometry','objects':p1},{'id':'composites','objects':p2},{'id':'data','objects':p3}]}
        write_json(stage/'scene.json',scene);build(stage/'scene.json',stage/'native-specimens.pptx');audit=inspect(stage/'native-specimens.pptx',stage/'scene.json');write_json(stage/'structure-audit.json',audit)
        write_json(stage/'semicircle.spec.json',{'id':'metric','recipe':'flat_semicircle','bbox':[40,40,240,120],'evidence':EV})
        write_json(stage/'patch.spec.json',{'base_sha256':sha256(stage/'scene.json'),'allowed_ids':['geometry/title'],'reason':'Synthetic bounded title edit','changes':[{'slide':'geometry','id':'title','op':'set_text','value':'Native geometry / revised'}]})
        patch_scene(stage/'scene.json',json.loads((stage/'patch.spec.json').read_text()),stage/'patched');build(stage/'patched/scene.json',stage/'patched/native-specimens-patched.pptx')
        placement_report(assets/'synthetic-icon.png',[100,100,140,140],stage/'asset-layout')
        fontspec={'text':'Cu(II)  100 μM  /  Native text','candidates':[{'font':'DejaVu Sans','font_size_pt':25},{'font':'Liberation Sans','font_size_pt':25},{'font':'DejaVu Sans','font_size_pt':25,'bold':True}],'canvas':[1000,300],'sample_bbox':[40,110,920,105]}
        write_json(stage/'fonts.spec.json',fontspec);font_sheet(fontspec,stage/'fonts')
        report={'status':'built_not_visual_approved','native_pages':3,'font_pages':3,'optional_boolean':optional,'structure':audit['checks'],'next':'Render with actual PowerPoint; inspect full pages and component regions. Do not submit this synthetic example as a user reconstruction.'}
        write_json(stage/'demo-report.json',report)
    return {'status':'built','outdir':str(outdir),'specimens':'native-specimens.pptx','font_specimens':'fonts/font-candidates.pptx','visual_review':'not_run'}
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--outdir',type=Path,required=True);args=ap.parse_args();print(json.dumps(run(args.outdir),ensure_ascii=False,indent=2))
