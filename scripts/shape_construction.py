"""Bounded parametric geometry and explicit-mask contour measurements."""
from __future__ import annotations
import base64
import copy
import io
import math

from graphics_geometry import check_commands, flatten
from graphics_recipe import compile_recipe

def construct(a):
    from shapely.geometry import Polygon
    mode=a['mode']; oid=a['id']
    recipe={'format':'graphics-recipe/1','id':oid,'canvas':a['canvas'],
            'points_per_unit':a.get('points_per_unit',1),'order':['result']}
    warnings=[]
    if mode=='rounded_polygon':
        points=a['points']; polygon=Polygon(points)
        if len({tuple(p) for p in points})!=len(points): raise ValueError('Duplicate vertices')
        if not polygon.is_valid or polygon.area<0.01: raise ValueError('Self-intersecting or degenerate polygon')
        pairs=list(zip(points,points[1:]+points[:1]))
        lengths=[math.dist(p,q) for p,q in pairs]
        if min(lengths)<0.12: raise ValueError('Edge shorter than 0.12 units')
        inset=a['corner_inset']
        if inset>0.48*min(lengths): raise ValueError('corner_inset exceeds 48 percent of shortest edge')
        if inset==0:
            commands=[['M',*points[0]]]+[['L',*p] for p in points[1:]]+[['Z']]
        else:
            signs=[];before=[];after=[]
            for i,p in enumerate(points):
                prev,nxt=points[i-1],points[(i+1)%len(points)]
                u=[prev[j]-p[j] for j in range(2)];v=[nxt[j]-p[j] for j in range(2)]
                signs.append(u[0]*v[1]-u[1]*v[0])
                before.append([p[j]+u[j]*inset/lengths[i-1] for j in range(2)])
                after.append([p[j]+v[j]*inset/lengths[i] for j in range(2)])
            if any(abs(s)<1e-9 for s in signs) or min(signs)*max(signs)<0:
                raise ValueError('Rounded concave or collinear vertices unsupported; use corner_inset=0 or explicit curves')
            commands=[['M',*after[-1]]]
            for p,left,right in zip(points,before,after):
                commands += [['L',*left],['C',*[left[j]+(p[j]-left[j])*2/3 for j in range(2)],
                                         *[right[j]+(p[j]-right[j])*2/3 for j in range(2)],*right]]
            commands.append(['Z'])
            warnings.append('corner_inset is edge setback, not an exact circular radius')
        recipe['paths']=[{'id':'result','closed':True,'commands':commands,'style':a['style']}]
    else:
        check_commands(a['commands'])
        if a['commands'][-1]!=['Z']: raise ValueError('Radial seed must be closed')
        cx,cy=a['center'];angle=math.radians(a.get('step_deg',360/a['count']))
        c,s=math.cos(angle),math.sin(angle)
        recipe['paths']=[{'id':'seed','visible':False,'closed':True,'commands':copy.deepcopy(a['commands']),'style':a['style']}]
        recipe['curve_groups']=[{'id':'result','mode':'affine_repeat','source':'seed','count':a['count'],
                                 'matrix_step':[c,s,-s,c,cx-c*cx+s*cy,cy-s*cx-c*cy]}]
        warnings.append('Geometry rotates; stored gradient angle remains unchanged')
    result=compile_recipe(recipe)
    def visit(objects):
        for o in objects:
            if o['kind']=='group':yield from visit(o['children'])
            else:yield o
    for o in visit(result['objects']):
        rings=flatten(o['commands'])
        for ring in rings:
            if not Polygon(ring).is_valid: raise ValueError('Constructed path is self-intersecting')
        for cmd in o['commands']:
            for j in range(1,len(cmd),2):
                if not (0<=cmd[j]<=a['canvas'][0] and 0<=cmd[j+1]<=a['canvas'][1]):
                    raise ValueError('Geometry leaves requested canvas')
    return {'recipe':recipe,'objects':result['objects'],'warnings':warnings,
            'office':'not_run','visual_review':'pending','scope':'draft_not_adopted'}

def compare_contours(reference,candidate,reference_mask,candidate_mask,exclude=None):
    import numpy as np
    from scipy.ndimage import binary_erosion,binary_dilation,distance_transform_edt,shift
    from PIL import Image
    size=reference.size
    if any(im.size!=size for im in [candidate,reference_mask,candidate_mask]+([exclude] if exclude else [])):
        raise ValueError('Images and masks must have the same explicit pixel frame')
    if size[0]*size[1]>1_000_000: raise ValueError('Contour crop exceeds one million pixels')
    def mask(im):
        raw=np.asarray(im.convert('L'))
        if not np.isin(raw,[0,255]).all():raise ValueError('Masks must be explicit binary 0/255, not antialiased grayscale')
        return raw==255
    r,c=mask(reference_mask),mask(candidate_mask)
    excluded=mask(exclude) if exclude else np.zeros(r.shape,dtype=bool)
    valid=~binary_dilation(excluded,iterations=1) if excluded.any() else ~excluded
    def edge(m):return (m & ~binary_erosion(m,border_value=0)) & valid
    re,ce=edge(r),edge(c)
    if min(re.sum(),ce.sum())<3:raise ValueError('Insufficient visible contour after exclusions')
    def metrics(x,y):
        a=distance_transform_edt(~y)[x];b=distance_transform_edt(~x)[y]
        v=np.concatenate([a,b])
        return {'reference_samples':int(x.sum()),'candidate_samples':int(y.sum()),
                'mean_px':float(v.mean()),'p50_px':float(np.percentile(v,50)),
                'p95_px':float(np.percentile(v,95)),'max_px':float(v.max()),
                'over_1px_samples':int((v>1).sum()),'over_2px_samples':int((v>2).sum()),
                'histogram_bins_px':[0,0.5,1,2,4,8,'inf'],
                'histogram_counts':np.histogram(v,[0,.5,1,2,4,8,np.inf])[0].tolist()}
    ry,rx=np.nonzero(r & ~excluded);cy,cx=np.nonzero(c & ~excluded)
    if not len(rx) or not len(cx):raise ValueError('Empty visible foreground')
    delta=[float(rx.mean()-cx.mean()),float(ry.mean()-cy.mean())]
    shifted=shift(c.astype('uint8'),(delta[1],delta[0]),order=0,mode='constant',cval=0).astype(bool)
    se=edge(shifted)
    aligned=metrics(re,se) if se.sum()>=3 and shifted.sum()==c.sum() else None
    left=np.asarray(reference.convert('RGB'),dtype=float);right=np.asarray(candidate.convert('RGB'),dtype=float)
    overlay=((left+right)*.25+127).clip(0,255).astype('uint8')
    overlay[re]=[235,65,100];overlay[ce]=[35,145,245];overlay[re & ce]=[50,190,95]
    overlay[excluded]=[160,160,160]
    image=Image.fromarray(overlay);stream=io.BytesIO();image.save(stream,format='PNG')
    return {'format':'contour-comparison/1','size_px':list(size),'raw':metrics(re,ce),
            'centroid_translation_candidate_to_reference_px':delta,'centroid_aligned':aligned,
            'centroid_note':'Estimate from visible binary foreground, not registration truth; aligned numbers never replace raw distances',
            'unmatched_reference_area_px':int((r & ~c & ~excluded).sum()),
            'unmatched_candidate_area_px':int((c & ~r & ~excluded).sum()),
            'excluded_px':int(excluded.sum()),'exclusion_boundary_guard_px':1,
            'overlay':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(),
            'visual_review':'not_assessed','source_fidelity':'not_assessed',
            'limitations':['Mask attribution is supplied by caller','No automatic score or approval','Binary mask discards antialiasing']}
