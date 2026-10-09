"""Bounded fixed-alpha multilayer fitting with spatial holdout and quantized scoring."""
import time
import numpy as np
from graphics_gradient import positions
from graphics_paint import mix,profile

def fit(image,mask,options):
    from scipy.optimize import least_squares
    if mask is None or mask.size!=image.size: raise ValueError('Explicit same-size visible-region mask required')
    if list(image.size)!=options['frame']: raise ValueError('Frame must equal reference crop dimensions')
    rgba=np.asarray(image.convert('RGBA'));valid=(np.asarray(mask.convert('L'))>127)&(rgba[:,:,3]==255)
    yy,xx=np.nonzero(valid)
    if len(xx)<128: raise ValueError('Insufficient visible samples')
    w,h=image.size
    if min(w,h)<8 or np.ptp(xx)<w*.25 or np.ptp(yy)<h*.25: raise ValueError('Insufficient spatial coverage')
    rng=np.random.default_rng(73021);take=rng.choice(len(xx),min(len(xx),1024),replace=False)
    xx,yy=xx[take],yy[take];xy=np.c_[(xx+.5)/w,(yy+.5)/h];rgb=rgba[yy,xx,:3]/255.
    hold=((xx*8//w)+(yy*8//h))%4==0
    if min(hold.sum(),(~hold).sum())<24: raise ValueError('Insufficient held-out spatial tiles')
    background=np.array([int(options['background'][j:j+2],16)/255 for j in (0,2,4)])
    components=options['components'];counts=options['layer_counts'];start=time.monotonic();candidates=[]
    if len({c['id'] for c in components})!=len(components): raise ValueError('Duplicate component ID')
    timed_out=False
    def color(c): return ''.join(f'{n:02X}' for n in np.rint(np.clip(c,0,1)*255).astype(int))
    for count in counts:
        selected=components[:count]
        if len(selected)!=count: raise ValueError('Layer count exceeds ordered components')
        def predict(colors,coords):
            out=np.broadcast_to(background,(len(coords),3)).copy()
            for i,comp in enumerate(selected):
                t=positions(coords,w,h,'linear',[comp['angle_deg']])
                a=comp['fill_alpha']*comp['stop_alpha']
                out=out*(1-a)+mix(t,[0,1],colors[i])*a
            return out
        def residual(p):
            if time.monotonic()-start>options.get('timeout_seconds',20): raise TimeoutError()
            return (predict(p.reshape(count,2,3),xy[~hold])-rgb[~hold]).ravel()
        initial=np.tile(np.median(rgb[~hold],axis=0),(count,2,1))
        try:
            fit=least_squares(residual,np.clip(initial.ravel(),.001,.999),bounds=(0,1),max_nfev=60,loss='soft_l1',f_scale=.025)
        except TimeoutError:
            timed_out=True;break
        quantized=np.rint(fit.x.reshape(count,2,3)*255)/255
        error=float(np.abs(predict(quantized,xy[hold])-rgb[hold]).mean())
        layers=[{'id':c['id'],'style':{'line':None,'fill_alpha':c['fill_alpha'],
                 'gradient':{'type':'linear','angle_deg':c['angle_deg'],'stops':[
                 {'position':j,'color':color(quantized[i,j]),'alpha':c['stop_alpha']} for j in range(2)]}}}
                 for i,c in enumerate(selected)]
        effective=[c['fill_alpha']*c['stop_alpha'] for c in selected]
        candidates.append({'layers':layers,'layer_count':count,'validation_mae':error,
            'score':error+.001*count,'effective_alpha':effective,
            'background_transmission':float(np.prod(1-np.array(effective))),
            'optimizer_converged':bool(fit.success)})
    candidates.sort(key=lambda c:c['score'])
    return {'model':'layered_linear','candidates':candidates,'selected':candidates[0] if candidates else None,
            'training_samples':int((~hold).sum()),'validation_samples':int(hold.sum()),
            'holdout':'spatial 8x8 tiles; excluded from optimization',
            'profile':profile()['id'],'provenance':options['provenance'],'frame':options['frame'],
            'background':options['background'],'elapsed_seconds':time.monotonic()-start,'timed_out':timed_out,
            'warnings':['Fixed supplied angles and alpha; original layers are not uniquely identifiable',
                        'Quantized RGB proposal requires actual Office comparison'],
            'adopted':False,'office':'not_run','visual_review':'pending'}
