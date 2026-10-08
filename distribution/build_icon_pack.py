"""Explicit maintainer fetch of pinned public GitHub SVGs; never runs at startup."""
from __future__ import annotations
import concurrent.futures, hashlib, json, sys, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox_manager.icons.geometry import compile_svg

def fetch(spec):
    url=f"https://raw.githubusercontent.com/{spec['repo']}/{spec['revision']}/{urllib.request.quote(spec['path'])}"
    req=urllib.request.Request(url,headers={'User-Agent':'PPTToolbox-icon-pack-builder'})
    raw=urllib.request.urlopen(req,timeout=45).read(500001)
    if len(raw)>400000:raise ValueError('SVG exceeds size limit')
    svg=raw.decode('utf-8-sig');compile_svg(svg)
    return {'svg':svg,'metadata':{'name':spec['name'],'aliases':[Path(spec['path']).stem],
        'tags':spec['tags'],'collection':spec['collection'],'style':spec['style'],'author':spec['author'],
        'license':spec['license'],'source_url':f"https://github.com/{spec['repo']}/blob/{spec['revision']}/{spec['path']}",
        'source_revision':spec['revision'],'origin':'library','notes':'Pinned upstream SVG; native placement requires Office review'}}

def main():
    sources=json.loads((ROOT/'distribution/icon-pack-sources.json').read_text(encoding='utf-8'))
    items=[];failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        tasks={pool.submit(fetch,s):s for s in sources}
        for task in concurrent.futures.as_completed(tasks):
            spec=tasks[task]
            try:items.append(task.result())
            except Exception as exc:failures.append({'source':spec,'error':str(exc)})
    items.sort(key=lambda x:x['metadata']['source_url'])
    out=ROOT/'assets/icon-packs';out.mkdir(parents=True,exist_ok=True)
    (out/'curated.json').write_text(json.dumps({'id':'curated-20260928','items':items},ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=ROOT/'checks/icon-library-20260928';evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'upstream-import.json').write_text(json.dumps({'accepted':len(items),'rejected':failures},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'accepted':len(items),'failed':len(failures),'collections':{c:sum(i['metadata']['collection']==c for i in items) for c in {i['metadata']['collection'] for i in items}}}))
if __name__=='__main__':main()
