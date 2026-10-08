"""Bounded text envelopes for an authorized local patch, never visual approval."""
import math


def valid_box(value):
    return (isinstance(value,list) and len(value)==4
            and all(type(v) in (int,float) and math.isfinite(v) for v in value)
            and value[2]>0 and value[3]>0)


def scope(before, after, old_props, new_props, ids, slide, canvas, size, hashes):
    result={'status':'measured','boxes':[], 'unverified':[], 'intersections':[],
            'scope':'Unrotated root text; actual old/new Office bounds, 2px fringe; visual review remains required'}
    targets=[oid for oid in ids if any(p.get(f'{slide-1}/{oid}',{}).get('text')
                                     for p in (old_props,new_props))]
    if not targets:return result
    width,height=size; sx=width/canvas['width_pt'];sy=height/canvas['height_pt']
    for label,receipt,props,expected in [('before',before,old_props,hashes[0]),('after',after,new_props,hashes[1])]:
        if (receipt.get('status')!='passed' or receipt.get('renderer')!='Microsoft PowerPoint'
                or receipt.get('pptx_sha256')!=expected):
            result['unverified'].append({'phase':label,'reason':'receipt_identity'});continue
        rows=receipt.get('text_bounds',[])
        if not isinstance(rows,list):rows=[]
        rows=[r for r in rows if isinstance(r,dict) and r.get('slide')==slide]
        for oid in targets:
            p=props.get(f'{slide-1}/{oid}',{})
            found=[r for r in rows if r.get('id')==oid]
            if not p.get('text'):continue  # A text deletion has no new glyph envelope.
            if (p.get('parent') or abs(p.get('rotation',0))>.01 or len(found)!=1
                    or found[0].get('status')=='blocked' or not valid_box(found[0].get('bound_pt'))
                    or type(found[0].get('rotation')) not in (float,int) or abs(found[0]['rotation'])>.01
                    or not valid_box(found[0].get('box_pt'))
                    or any(abs(a-b)>.5 for a,b in zip(found[0]['box_pt'],p['bbox_pt']))):
                result['unverified'].append({'object_id':oid,'phase':label,'reason':'missing_or_unsupported_text_measurement'});continue
            x,y,w,h=found[0]['bound_pt']
            box=[max(0,math.floor(x*sx)-2),max(0,math.floor(y*sy)-2),
                 min(width,math.ceil((x+w)*sx)+2),min(height,math.ceil((y+h)*sy)+2)]
            if box[0]>=box[2] or box[1]>=box[3]:
                result['unverified'].append({'object_id':oid,'phase':label,'reason':'text_outside_canvas'});continue
            result['boxes'].append({'id':f'text-{label}-{len(result["boxes"])}','bbox':box})
            for other in rows:
                if other.get('id') in ids or not valid_box(other.get('bound_pt')):continue
                a,b,c,d=other['bound_pt']
                if min(x+w,a+c)>max(x,a) and min(y+h,b+d)>max(y,b):
                    result['intersections'].append({'object_id':oid,'neighbor_id':other.get('id'),'phase':label})
    if result['unverified']:result['status']='not_assessed'
    elif result['intersections']:result['status']='needs_review'
    return result
