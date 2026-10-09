"""Bounded native-path fitter extracted from the layered-pen case.
Geometry diagnostics only. No image classification, Office, adoption or acceptance.
"""
import copy, math
import numpy as np
from scipy.interpolate import splprep,splev
from scipy.spatial import cKDTree
from shapely.geometry import LinearRing, Polygon

MAX_SAMPLES=40000
def leaves(o,depth=0):
 if depth>16:raise ValueError('Fragment nesting exceeds 16')
 if o.get('kind')=='group':
  for c in o.get('children',[]):yield from leaves(c,depth+1)
 else:yield o

def contours(commands,step=.06):
 out=[];pts=[];cur=None;total=0
 def append_segment(a,end,controls=None):
  nonlocal total
  length=np.linalg.norm(end-a) if controls is None else sum(np.linalg.norm(y-x) for x,y in zip([a,*controls[:-1]],controls))
  n=max(2,int(math.ceil(length/step))+1);total+=n
  if total>MAX_SAMPLES:raise ValueError('Path sampling budget exceeded')
  t=np.linspace(0,1,n)[1:,None]
  values=(1-t)*a+t*end if controls is None else (1-t)**3*a+3*(1-t)**2*t*controls[0]+3*(1-t)*t*t*controls[1]+t**3*end
  pts.extend(values)
 for q in commands:
  op=q[0]
  if op=='M':
   if pts:out.append((np.array(pts),False))
   cur=np.array(q[1:],dtype=float);pts=[cur.copy()]
  elif op in ('L','C'):
   if cur is None:raise ValueError('Path must start with M')
   v=np.array(q[1:],dtype=float).reshape(-1,2);append_segment(cur,v[-1],None if op=='L' else v);cur=v[-1]
  elif op=='Z':
   if not pts:raise ValueError('Empty closed ring')
   if np.linalg.norm(pts[-1]-pts[0])>1e-9:append_segment(cur,pts[0])
   out.append((np.array(pts),True));pts=[];cur=None
 if pts:out.append((np.array(pts),False))
 return out

def validate_fragment(fragment):
 ids=set();count=0;commands=0
 for p in leaves(fragment):
  count+=1
  if count>128:raise ValueError('Fragment exceeds 128 leaves')
  identifier=p.get('id')
  if not isinstance(identifier,str) or not identifier or identifier in ids:raise ValueError('Missing or duplicate leaf ID')
  ids.add(identifier)
  if p.get('kind')!='path':continue
  cs=p.get('commands')
  if not isinstance(cs,list) or not cs:raise ValueError('Missing path commands')
  commands+=len(cs)
  if commands>10000:raise ValueError('Command budget exceeded')
  for q in cs:
   if not isinstance(q,list) or not q or q[0] not in ('M','L','C','Z') or len(q)!={'M':3,'L':3,'C':7,'Z':1}[q[0]]:raise ValueError('Expected M/L/C/Z commands')
   if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>100000 for x in q[1:]):raise ValueError('Invalid coordinates')

def nesting(rings):
 polygons=[Polygon(p) for p,closed in rings]
 if any(not p.is_valid or p.area<1e-8 for p in polygons):return None
 if any(p.boundary.intersects(q.boundary) for i,p in enumerate(polygons) for q in polygons[i+1:]):return None
 return [[p.contains(q) for q in polygons] for p in polygons]
def signed_area(p):return .5*np.sum(p[:-1,0]*p[1:,1]-p[1:,0]*p[:-1,1])

def curve_fit(p,rms,anchors):
 p=p[np.r_[True,np.linalg.norm(np.diff(p,axis=0),axis=1)>1e-7]]
 d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
 u=np.linspace(0,d[-1],min(MAX_SAMPLES,max(24,int(d[-1]*4))))
 # Insert nearest source samples for semantic anchors into the parameter grid.
 aq=[d[np.argmin(np.linalg.norm(p-np.asarray(a),axis=1))] for a in anchors]
 u=np.unique(np.r_[u,aq]);q=np.c_[np.interp(u,d,p[:,0]),np.interp(u,d,p[:,1])];w=np.ones(len(q))
 for a in aq:w[np.argmin(abs(u-a))]=1000
 tck,_=splprep(q.T,w=w,s=len(q)*rms*rms,per=True,k=3)
 knots=np.unique(tck[0]);knots=knots[(knots>=0)&(knots<=1)];cmd=[['M',*splev(0,tck)]]
 for a,b in zip(knots[:-1],knots[1:]):
  x=np.array(splev(a,tck));y=np.array(splev(b,tck));h=(b-a)/3
  cmd.append(['C',*(x+h*np.array(splev(a,tck,der=1))),*(y-h*np.array(splev(b,tck,der=1))),*y])
 cmd.append(['Z']);return [[q[0]]+[round(float(v),6) for v in q[1:]] for q in cmd],q[[np.argmin(abs(u-a)) for a in aq]]

def fit_fragment(fragment,rms,max_error,anchors):
 validate_fragment(fragment)
 if not (0<rms<=5 and 0<max_error<=10):raise ValueError("Invalid fitting tolerance")
 result=copy.deepcopy(fragment);records=[]
 known={p['id'] for p in leaves(result) if p['kind']=='path'}
 if set(anchors)-known:raise ValueError('Unknown anchor path IDs: '+str(sorted(set(anchors)-known)))
 for obj in leaves(result):
  if obj['kind']!='path':continue
  rings=contours(obj['commands'],step=.06)
  if any(not closed for _,closed in rings):
   if anchors.get(obj['id']):raise ValueError('Anchors on open or mixed paths are unsupported')
   records.append(dict(id=obj['id'],status='unchanged_open_path'));continue
  assigned={i:[] for i in range(len(rings))}
  for a in anchors.get(obj['id'],[]):
   distances=[cKDTree(p).query(a)[0] for p,_ in rings];nearest=int(np.argmin(distances))
   if distances[nearest]>max_error:raise ValueError('Anchor is outside the permitted source-contour distance')
   assigned[nearest].append(a)
  before_nesting=nesting(rings)
  if before_nesting is None:
   records.append(dict(id=obj["id"],status="preserved_invalid_or_touching_rings"));continue
  start_record=len(records)
  output=[];valid=True
  for index,(p,_) in enumerate(rings):
   local=assigned[index]
   accepted=False
   for attempt in range(9):
    amount=rms*.65**attempt
    try:
     cmd,locked=curve_fit(p,amount,local);c=contours(cmd,step=.06)[0][0]
    except (ValueError,TypeError,RuntimeError):
     records.append(dict(id=obj['id'],ring=index,status='preserved_fit_or_sampling_failure'));valid=False;break
    ds=np.r_[cKDTree(p).query(c)[0],cKDTree(c).query(p)[0]]
    anchor_error=max(cKDTree(c).query(locked)[0],default=0.)
    topology=bool(LinearRing(c).is_simple and signed_area(p)*signed_area(c)>0)
    if topology and ds.max()<=max_error and anchor_error<=.08:
     output+=cmd;accepted=True;break
   if not valid:break
   records.append(dict(id=obj['id'],ring=index,status='fitted' if accepted else 'preserved_after_failed_constraint',rms=amount,max_distance=float(ds.max()),p95_distance=float(np.percentile(ds,95)),anchor_count=len(local),anchor_distance=float(anchor_error),topology_checked=topology))
   if not accepted:valid=False;break
  if valid and nesting(contours(output))!=before_nesting:
   valid=False;records.append(dict(id=obj['id'],status='preserved_nesting_change'))
  if valid:obj['commands']=output
  else:
   for record in records[start_record:]:
    if record.get('status')=='fitted':record['status']='discarded_with_preserved_path'
  for record in records[start_record:]:record['adopted_in_candidate']=valid
 return result,records
