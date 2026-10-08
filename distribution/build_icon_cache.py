"""Extract only verified bundled derivatives from a local conversion database."""
import argparse,base64,gzip,json,sqlite3,hashlib
from pathlib import Path


def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def build(packs,database):
    report=[]
    with sqlite3.connect('file:'+database.resolve().as_posix()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for path in sorted(packs.glob('*.json')):
            raw=path.read_bytes();pack=json.loads(raw)
            registered=db.execute('SELECT digest FROM packs WHERE id=?',(pack['id'],)).fetchone()
            if not registered or registered[0]!=sha(raw):raise ValueError('Pack differs from donor '+path.name)
            candidates={}
            for row in db.execute('SELECT i.* FROM icons i JOIN pack_icons p ON p.version=i.version WHERE p.pack=?',(pack['id'],)):
                candidates.setdefault(sha(row['source'].encode()),[]).append(dict(row))
            selected=[]
            for item in pack['items']:
                expected={k:item['metadata'].get(k) for k in ('name','aliases','tags','collection','style','author','license','source_url','source_revision','origin','notes')}
                for key in ('aliases','tags'):
                    if expected[key] is None:expected[key]=[]
                found=[]
                for row in candidates.get(sha(item['svg'].encode()),[]):
                    meta=json.loads(row['metadata'])
                    if meta.get('parent') is None and all(meta.get(k)==v for k,v in expected.items()):found.append(row)
                if len(found)!=1:raise ValueError('Ambiguous or absent derivative '+item['metadata']['name'])
                row=found[0];meta=json.loads(row['metadata'])
                if row['version']!=sha(canonical({'source':row['source'],'metadata':meta}).encode()):raise ValueError('Version identity mismatch')
                public={k:row[k] for k in ('version','metadata','source','normalized','recipe','fingerprint','geometry_hash')}
                public['preview']=base64.b64encode(row['preview']).decode()
                selected.append(public)
            payload={'converter_version':'1.0.0','pack_sha256':sha(raw),'rows':selected}
            out=path.with_suffix('.cache.json.gz');out.write_bytes(gzip.compress(canonical(payload).encode(),mtime=0))
            report.append({'pack':path.name,'icons':len(selected),'cache_sha256':sha(out.read_bytes()),'bytes':out.stat().st_size})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--packs',type=Path,required=True);p.add_argument('--database',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.packs,a.database),indent=2))
