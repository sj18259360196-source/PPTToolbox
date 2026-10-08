"""Atomic immutable icon versions, provenance, drafts and local visual retrieval."""
from __future__ import annotations
import base64, contextlib, hashlib, io, json, re, sqlite3, time, uuid
from pathlib import Path
from PIL import Image
from .geometry import compile_svg, svg_from_ir, render, fingerprint, scene_group

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()
def stamp():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())

def attribution(meta):
    license_id=meta.get('license','')
    urls={'CC-BY-3.0':'https://creativecommons.org/licenses/by/3.0/',
          'CC-BY-4.0':'https://creativecommons.org/licenses/by/4.0/',
          'CC0-1.0':'https://creativecommons.org/publicdomain/zero/1.0/',
          'MIT':'https://opensource.org/license/mit/',
          'Apache-2.0':'https://www.apache.org/licenses/LICENSE-2.0',
          'ISC':'https://opensource.org/license/isc-license-txt/'}
    result={'title':meta.get('name',''),'author':meta.get('author',''),'license':license_id,
            'license_url':urls.get(license_id,''),'source_url':meta.get('source_url',''),
            'source_revision':meta.get('source_revision',''),
            'changes':'SVG converted to editable PowerPoint paths; placement may change size, color and stroke.'}
    result['text']='\n'.join(str(v) for v in result.values() if v)
    return result

class Library:
    def __init__(self,root):
        from ..policy import plain_path
        self.root=plain_path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=plain_path(self.root/'icons.sqlite3')
        if self.path.exists() and self.path.stat().st_nlink>1:raise ValueError('图标数据库不能是硬链接')
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS icons (
              version TEXT PRIMARY KEY, family TEXT NOT NULL, created TEXT NOT NULL,
              metadata TEXT NOT NULL, source TEXT NOT NULL, normalized TEXT NOT NULL,
              recipe TEXT NOT NULL, preview BLOB NOT NULL, fingerprint TEXT NOT NULL,
              geometry_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft');
            CREATE TABLE IF NOT EXISTS reviews (
              id TEXT PRIMARY KEY, version TEXT NOT NULL, created TEXT NOT NULL,
              kind TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packs (id TEXT PRIMARY KEY, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pack_icons (pack TEXT NOT NULL, version TEXT NOT NULL, PRIMARY KEY(pack,version));
            CREATE INDEX IF NOT EXISTS icons_geometry_hash ON icons(geometry_hash);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, created TEXT NOT NULL, brief TEXT NOT NULL,
              reference BLOB, attempts INTEGER NOT NULL DEFAULT 0, versions TEXT NOT NULL DEFAULT '[]');
            ''')
    @contextlib.contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()

    def save(self,svg,metadata,parent=None,reference=None,*,_prepared=None):
        if not isinstance(metadata,dict):raise ValueError('需要图标来源信息')
        meta={k:metadata.get(k) for k in ('name','aliases','tags','collection','style','author','license','source_url','source_revision','origin','notes')}
        for key in ('name','author','license','origin'):
            if not isinstance(meta[key],str) or not meta[key].strip():raise ValueError('缺少图标信息 '+key)
        if meta['origin'] not in {'library','self_drawn','traced','model'}:raise ValueError('无效图标来源类型')
        if meta['origin']=='library' and not meta['source_url']:raise ValueError('外部素材需要原始来源 URL')
        for key in ('tags','aliases'):
            if meta[key] is None:meta[key]=[]
            if not isinstance(meta[key],list) or any(not isinstance(v,str) for v in meta[key]):raise ValueError('标签与别名需要文本列表')
        if len(canonical(meta))>12000:raise ValueError('图标元数据过长')
        from ..artwork_preflight import prepare
        prepared=_prepared if _prepared is not None else prepare(svg)
        ir=prepared['ir'];normalized=prepared['normalized'];png=base64.b64decode(prepared['png'])
        meta['parent']=parent;meta['source_sha256']=digest(svg);meta['normalized_sha256']=digest(normalized)
        meta['converter_version']='1.0.0'
        if parent:self.row(parent)
        version=digest(canonical({'source':svg,'metadata':meta}))
        shape_key=digest(canonical([{k:v for k,v in p.items() if k!='name'} for p in ir['parts']]))
        family=self.row(parent)['family'] if parent else version
        with self.db() as db:
            duplicate=db.execute('SELECT version FROM icons WHERE version=?',(version,)).fetchone()
            db.execute('INSERT OR IGNORE INTO icons VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (version,family,stamp(),canonical(meta),svg,normalized,canonical(ir),png,canonical(fingerprint(png)),shape_key,'draft'))
            similar=[r['version'] for r in db.execute('SELECT version FROM icons WHERE geometry_hash=? AND version<>? LIMIT 5',(shape_key,version))]
        if not duplicate:
            if reference is not None:self.validate(version,reference)
            else:
                with self.db() as db:
                    db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',
                        (uuid.uuid4().hex,version,stamp(),'structural',canonical(prepared['structural'])))
        return {**self.inspect(version),'duplicate':bool(duplicate),'same_geometry':similar}

    def row(self,version):
        if not isinstance(version,str) or not re.fullmatch('[a-f0-9]{64}',version):raise ValueError('无效图标版本')
        with self.db() as db:row=db.execute('SELECT * FROM icons WHERE version=?',(version,)).fetchone()
        if not row:raise ValueError('图标版本不存在')
        return dict(row)

    def inspect(self,version,content=False):
        r=self.row(version);ir=json.loads(r['recipe']);meta=json.loads(r['metadata'])
        with self.db() as db:reviews=[json.loads(x['result'])|{'kind':x['kind'],'created':x['created']} for x in db.execute('SELECT * FROM reviews WHERE version=? ORDER BY created',(version,))]
        out={'version':version,'family':r['family'],'created':r['created'],'metadata':meta,'status':r['status'],
             'attribution':attribution(meta),
             'part_count':len(ir['parts']),'node_count':sum(len(p['commands']) for p in ir['parts']),
             'width':ir['width'],'height':ir['height'],'reviews':reviews,'editable':'native_paths',
             'preview':'data:image/png;base64,'+base64.b64encode(r['preview']).decode()}
        if content:out.update(svg=r['normalized'],source_svg=r['source'],recipe=ir)
        return out

    def search(self,query='',collection='',style='',include_drafts=False,limit=30,reference=None):
        limit=max(1,min(int(limit),100));tokens=query.casefold().split()
        if len(query)>500:raise ValueError('检索词过长')
        ref=fingerprint(reference) if reference else None
        fields='version,metadata,status'+(',fingerprint' if reference else '')
        where=[];values=[]
        if not include_drafts:where.append("status IN ('reviewed','curated')")
        if collection:where.append("json_extract(metadata,'$.collection')=?");values.append(collection)
        if style:where.append("json_extract(metadata,'$.style')=?");values.append(style)
        sql='SELECT '+fields+' FROM icons'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY created DESC'
        with self.db() as db:rows=db.execute(sql,values).fetchall()
        ranked=[]
        for row in rows:
            m=json.loads(row['metadata'])
            if not include_drafts and row['status'] not in {'reviewed','curated'}:continue
            if collection and m.get('collection')!=collection:continue
            if style and m.get('style')!=style:continue
            hay=' '.join([m['name'],*m['aliases'],*m['tags']]).casefold()
            hits=sum(t in hay for t in tokens)
            if tokens and hits!=len(tokens):continue
            score=float(hits)
            distance=None
            if ref is not None:
                sample=json.loads(row['fingerprint'])
                if len(sample)!=len(ref):raise ValueError('Icon fingerprint size mismatch')
                distance=sum(abs(a-b) for a,b in zip(ref,sample))/len(ref)
                score+=1-distance
            ranked.append((score,row['version'],distance))
        ranked.sort(key=lambda x:(-x[0],x[1]))
        return {'total':len(ranked),'items':[self.inspect(v)|{'score':round(s,4),'appearance_distance':d} for s,v,d in ranked[:limit]],
                'method':'local_luminance_32x32' if reference else 'bilingual_tags',
                'note':'外观相似检索不判断科研语义，替换前须核对含义'}

    def validate(self,version,reference=None):
        import numpy as np
        r=self.row(version);ir=compile_svg(r['source'])
        if canonical(ir)!=r['recipe'] or svg_from_ir(ir)!=r['normalized']:raise ValueError('图标内容与固定版本不一致')
        def diff(a,b):
            a=Image.open(io.BytesIO(a)).convert('RGBA').resize((256,256));b=Image.open(io.BytesIO(b)).convert('RGBA').resize((256,256))
            values={}
            for color in ('white','black'):
                aa=Image.new('RGBA',a.size,color);aa.alpha_composite(a)
                bb=Image.new('RGBA',b.size,color);bb.alpha_composite(b)
                values[color]=round(float(np.abs(np.array(aa,dtype=float)-np.array(bb,dtype=float)).mean()/255),6)
            return values
        result={'source_hash_ok':True,'native_path_count':len(ir['parts']),'raster_objects':0,
                'svg_conversion_pixel_mae':diff(render(r['source']),r['preview']),
                'office':'not_run','visual_review':'pending','semantic_review':'pending',
                'reference_pixel_mae':diff(reference,r['preview']) if reference else None}
        with self.db() as db:db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(uuid.uuid4().hex,version,stamp(),'structural',canonical(result)))
        return result

    def review(self,version,decision,note,reviewer='owner'):
        self.row(version)
        if decision not in {'approve','reject'} or not isinstance(note,str) or not note.strip():raise ValueError('需要检查结论及说明')
        result={'decision':decision,'note':note[:4000],'reviewer':reviewer,'scope':'icon appearance and meaning; placement Office review still required'}
        with self.db() as db:
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(uuid.uuid4().hex,version,stamp(),'human',canonical(result)))
            db.execute('UPDATE icons SET status=? WHERE version=?',('reviewed' if decision=='approve' else 'rejected',version))
        return self.inspect(version)

    def batch(self,items):
        if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('每批可导入 1 到 100 个图标')
        results=[]
        for i,item in enumerate(items):
            try:results.append({'index':i,'ok':True,'icon':self.save(item['svg'],item['metadata'],item.get('parent'))})
            except Exception as exc:results.append({'index':i,'ok':False,'error':str(exc)})
        return {'items':results,'passed':sum(r['ok'] for r in results),'failed':sum(not r['ok'] for r in results)}

    def seed(self,pack_path):
        raw=Path(pack_path).read_bytes();key=digest(raw)
        pack=json.loads(raw)
        with self.db() as db:old=db.execute('SELECT digest FROM packs WHERE id=?',(pack['id'],)).fetchone()
        if old and old[0]==key:return
        cache=Path(pack_path).with_suffix('.cache.json.gz')
        if cache.is_file():
            import gzip
            compiled=json.loads(gzip.decompress(cache.read_bytes()))
            if compiled.get('pack_sha256')==key and compiled.get('converter_version')=='1.0.0':
                self.seed_compiled(pack,compiled)
                return
        versions=[]
        for item in pack['items']:
            info=self.save(item['svg'],item['metadata'])
            versions.append(info['version'])
            # Curated source is searchable without fabricating an Office/visual review.
            with self.db() as db:db.execute("UPDATE icons SET status='curated' WHERE version=? AND status='draft'",(info['version'],))
        with self.db() as db:
            previous={r[0] for r in db.execute('SELECT version FROM pack_icons WHERE pack=?',(pack['id'],))}
            for v in previous-set(versions):db.execute("UPDATE icons SET status='superseded' WHERE version=? AND status='curated'",(v,))
            db.execute('DELETE FROM pack_icons WHERE pack=?',(pack['id'],))
            db.executemany('INSERT INTO pack_icons VALUES(?,?)',[(pack['id'],v) for v in versions])
            db.execute('INSERT OR REPLACE INTO packs VALUES(?,?)',(pack['id'],key))

    def seed_compiled(self,pack,compiled):
        """Install bundled public derivatives; never import reviews or user records."""
        rows=compiled['rows']
        if len(rows)!=len(pack['items']):raise ValueError('Bundled icon cache count mismatch')
        prepared=[]
        for item,row in zip(pack['items'],rows):
            meta=json.loads(row['metadata'])
            expected={k:item['metadata'].get(k) for k in ('name','aliases','tags','collection','style','author','license','source_url','source_revision','origin','notes')}
            for key in ('aliases','tags'):
                if expected[key] is None:expected[key]=[]
            if row['source']!=item['svg'] or any(meta.get(k)!=v for k,v in expected.items()):
                raise ValueError('Bundled icon cache provenance mismatch')
            if (meta.get('parent') is not None or meta.get('source_sha256')!=digest(row['source'])
                or meta.get('normalized_sha256')!=digest(row['normalized'])
                or row['version']!=digest(canonical({'source':row['source'],'metadata':meta}))):
                raise ValueError('Bundled icon cache identity mismatch')
            preview=base64.b64decode(row['preview'],validate=True)
            prepared.append((row['version'],row['version'],stamp(),row['metadata'],row['source'],
                             row['normalized'],row['recipe'],preview,row['fingerprint'],row['geometry_hash'],'curated'))
        versions={r[0] for r in prepared}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT OR IGNORE INTO icons VALUES(?,?,?,?,?,?,?,?,?,?,?)',prepared)
            previous={r[0] for r in db.execute('SELECT version FROM pack_icons WHERE pack=?',(pack['id'],))}
            for version in previous-versions:
                db.execute("UPDATE icons SET status='superseded' WHERE version=? AND status='curated'",(version,))
            db.execute('DELETE FROM pack_icons WHERE pack=?',(pack['id'],))
            db.executemany('INSERT INTO pack_icons VALUES(?,?)',[(pack['id'],v) for v in versions])
            db.execute('INSERT OR REPLACE INTO packs VALUES(?,?)',(pack['id'],compiled['pack_sha256']))

    def start_redraw(self,brief,reference=None):
        if not isinstance(brief,str) or not brief.strip() or len(brief)>5000:raise ValueError('请描述图标含义、部件和风格')
        job=uuid.uuid4().hex
        with self.db() as db:db.execute('INSERT INTO jobs(id,created,brief,reference) VALUES(?,?,?,?)',(job,stamp(),brief,reference))
        return {'job':job,'max_attempts':3,'brief':brief,'instruction':
            '先检索已有图标。缺失时按语义部件编写 SVG，使用 id 命名部件；允许 path/circle/rect/ellipse/line/polygon/g。'
            '不要嵌入图片、文字、脚本、滤镜或外部资源。提交后查看预览和差异，最多三次；不足时保留草稿并报告。'
            '图像相似度不能代替语义核对。通过受管提交结果使用返回的 scene_fragment，不能覆盖项目旧文件。'}

    def submit_redraw(self,job,svg,metadata):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not row:raise ValueError('重绘任务不存在')
            if row['attempts']>=3:raise ValueError('已达到三次重绘上限，请检查结果并明确建立新任务')
            db.execute('UPDATE jobs SET attempts=attempts+1 WHERE id=?',(job,))
        versions=json.loads(row['versions'])
        info=self.save(svg,metadata,versions[-1] if versions else None,row['reference'])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=json.loads(db.execute('SELECT versions FROM jobs WHERE id=?',(job,)).fetchone()[0])
            db.execute('UPDATE jobs SET versions=? WHERE id=?',(canonical(current+[info['version']]),job))
        return {'job':job,'attempt':row['attempts']+1,'icon':info,'remaining':2-row['attempts']}

    def stats(self):
        with self.db() as db:
            rows=db.execute('SELECT status,COUNT(*) AS n FROM icons GROUP BY status').fetchall()
            metas=db.execute('SELECT metadata FROM icons').fetchall()
        return {'counts':{r['status']:r['n'] for r in rows},'collections':sorted({json.loads(r[0]).get('collection') or '个人图标' for r in metas}),
                'storage':str(self.root),'format':'editable-icon/1'}
