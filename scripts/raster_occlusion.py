"""Advisory alpha-aware overlap checks for root, unrotated images."""
import math
from PIL import Image
from common import bbox_to_points, resolve_asset
from text_regression import valid_box


def hints(scene, base, receipt, slide_index):
    result={'findings':[],'deferred_images':[],'visual_review':'required',
            'scope':'Nontransparent pixels above measured root text. Unrotated contain/cover/stretch images; masks and groups deferred. Intersections require actual composite review.'}
    if receipt.get('status')!='passed' or receipt.get('renderer')!='Microsoft PowerPoint':return result
    objects=scene['slides'][slide_index-1]['objects'];order={o['id']:i for i,o in enumerate(objects)}
    texts=[r for r in receipt.get('text_bounds',[]) if r.get('slide')==slide_index and r.get('id') in order
           and valid_box(r.get('bound_pt')) and r.get('rotation')==0 and r.get('status')!='blocked']
    for obj in objects:
        if obj['kind']=='group':
            result['deferred_images'].append({'id':obj['id'],'reason':'group_contents_not_assessed'});continue
        if obj['kind']!='image':continue
        if obj.get('rotation_deg',0) or obj.get('mask'):
            result['deferred_images'].append({'id':obj['id'],'reason':'rotation_or_mask_not_assessed'});continue
        try:
            with Image.open(resolve_asset(base,obj['asset'])) as image:
                if image.width*image.height>16_000_000:raise ValueError('Image too large for bounded hint')
                alpha=image.convert('RGBA').getchannel('A')
                x,y,w,h=bbox_to_points(obj['bbox'],scene['canvas'])
                if w<=0 or h<=0:raise ValueError('Invalid image frame')
                if obj.get('source_crop'):
                    cx,cy,cw,ch=obj['source_crop']
                    alpha=alpha.crop((cx,cy,cx+cw,cy+ch))
                elif obj.get('fit','contain')=='contain':
                    scale=min(w/alpha.width,h/alpha.height)
                    nw,nh=alpha.width*scale,alpha.height*scale
                    x,y,w,h=x+(w-nw)/2,y+(h-nh)/2,nw,nh
                elif obj.get('fit')=='cover':
                    scale=max(w/alpha.width,h/alpha.height)
                    vw,vh=w/scale,h/scale;cx,cy=(alpha.width-vw)/2,(alpha.height-vh)/2
                    alpha=alpha.crop((cx,cy,cx+vw,cy+vh))
                for text in texts:
                    if order[text['id']]>=order[obj['id']]:continue
                    a,b,c,d=text['bound_pt'];left,top=max(x,a),max(y,b);right,bottom=min(x+w,a+c),min(y+h,b+d)
                    if left>=right or top>=bottom:continue
                    box=(max(0,math.floor((left-x)/w*alpha.width)),max(0,math.floor((top-y)/h*alpha.height)),
                         min(alpha.width,math.ceil((right-x)/w*alpha.width)),min(alpha.height,math.ceil((bottom-y)/h*alpha.height)))
                    if alpha.crop(box).getbbox():
                        result['findings'].append({'kind':'raster_over_text','image_id':obj['id'],'text_id':text['id'],
                            'image_frame_pt':[x,y,w,h], 'source_crop':obj.get('source_crop'),
                            'nontransparent_bbox_px':list(alpha.getbbox()),
                            'intersection_pt':[left,top,right-left,bottom-top]})
                        if len(result['findings'])>=30:return {**result,'truncated':True}
        except (OSError,ValueError,KeyError) as exc:
            result['deferred_images'].append({'id':obj['id'],'reason':type(exc).__name__})
    return result
