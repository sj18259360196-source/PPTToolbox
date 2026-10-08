"""Shared UI/MCP/CLI boundary. Owner review is intentionally not an Agent tool."""
from __future__ import annotations
import base64, io, json, os, sys, uuid, subprocess, time
from pathlib import Path
from PIL import Image
from .library import Library, canonical, digest, attribution
from .geometry import scene_group, render, svg_from_ir

READS={'search','inspect','stats','providers','fragment','trace_fragment'}
WRITES={'import','batch','validate','redraw_start','redraw_submit','trace','place','model_generate'}

def image_bytes(value):
    if not value:return None
    if not isinstance(value,str) or len(value)>8_000_000:raise ValueError('参考图过大')
    raw=base64.b64decode(value.split(',',1)[-1],validate=True)
    im=Image.open(io.BytesIO(raw))
    if im.width*im.height>16_000_000:raise ValueError('参考图超过 1600 万像素')
    im.thumbnail((1024,1024));out=io.BytesIO();im.convert('RGBA').save(out,format='PNG')
    return out.getvalue()


def compute_fragment(arguments, timeout=30):
    """Timeout can end only this owned pure calculation, never Office or a writer."""
    argv=[sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('compute_worker.py'))]
    payload=json.dumps({'op':'trace_fragment','arguments':arguments},ensure_ascii=False)
    if len(payload.encode('utf-8'))>8_500_000:raise ValueError('Icon computation input too large')
    try:
        run=subprocess.run(argv,input=payload,capture_output=True,text=True,encoding='utf-8',
            timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Pure icon trace timed out; owned computation stopped. No library, project or Office write occurred.') from exc
    if run.returncode:raise ValueError('Icon trace failed: '+run.stderr[-1200:])
    if len(run.stdout.encode('utf-8'))>16_000_000:raise ValueError('Icon computation output too large')
    value=json.loads(run.stdout)
    if not isinstance(value,dict) or 'scene_fragment' not in value:raise ValueError('Invalid icon computation response')
    return value

class IconService:
    def __init__(self,manager):
        self.manager=manager
        self._library=None

    @property
    def library(self):
        if self._library is None:
            m=self.manager
            previous=getattr(m,'icon_activity',None)
            m.icon_activity={**(previous or {}),'phase':'initializing_library'}
            try:
                library=Library(m.data/'icon-library')
                for pack in sorted((m.root/'assets/icon-packs').glob('*.json')):library.seed(pack)
                self._library=library
            finally:
                m.icon_activity=previous
        return self._library

    def call(self,op,args=None,source='mcp'):
        from ..policy import PolicyDenied
        from .contracts import validate
        a=args or {};m=self.manager;p=m.package()
        if op not in READS|WRITES|{'review'}:raise ValueError('未知图标操作')
        if not p['enabled'] or not p['trusted']:raise PolicyDenied('当前工具包未启用或未信任')
        if not m.override(p['id'],'tool','icons.'+op,True):raise PolicyDenied('图标工具已停用')
        if op in WRITES and source!='owner' and not m.settings()['agent_execution_enabled']:raise PolicyDenied('Agent 执行未启用')
        if op=='review' and source!='owner':raise PolicyDenied('图标晋级需要界面中的人工检查')
        validate(op,a,source=='owner')
        if source != 'owner' and (
                op in {'redraw_submit','trace','model_generate'}
                or op == 'import' and a.get('metadata',{}).get('origin') != 'library'
                or op == 'batch' and any(i.get('metadata',{}).get('origin') != 'library' for i in a['items'])):
            raise PolicyDenied('自绘素材先保存在项目 assets。交付获认可后，经 toolbox_retrospective.assets 记录用户选择再保留到全局库。')
        with m.lock:
            from ..storage import stamp
            started_at=stamp()
            phase='native_trace' if op=='trace_fragment' else 'library_'+op
            m.icon_activity={**(getattr(m,'icon_activity',None) or {}),'phase':phase,'dispatched':True}
            try:
                out=self.dispatch(op,a)
                if op=='search' and source!='owner' and not a.get('include_previews',False):
                    out={**out,'items':[{k:v for k,v in row.items() if k not in {'preview','reviews'}} for row in out['items']],
                         'preview_omitted':True,'inspect_tool':'icons_inspect'}
                project=a.get('project') or (str(Path(out['directory']).parents[2]) if op=='place' else '')
                m.store.event('icons.'+op,'图标操作完成',source=source,details={'version':a.get('version'),'job':a.get('job'),'project':project,'started_at':started_at,'ended_at':stamp()})
                return out
            except Exception as exc:
                m.store.event('icons.'+op,'图标操作失败',status='error',source=source,details={'error':str(exc)[:600],'project':a.get('project'),'version':a.get('version'),'started_at':started_at,'ended_at':stamp()})
                raise

    def dispatch(self,op,a):
        if op=='trace_fragment':return compute_fragment(a)
        lib=self.library
        if op=='search':return lib.search(a.get('query',''),a.get('collection',''),a.get('style',''),a.get('include_drafts',False),a.get('limit',30),image_bytes(a.get('reference')))
        if op=='inspect':return lib.inspect(a['version'],True)
        if op=='stats':return lib.stats()
        if op=='import':return lib.save(a['svg'],a['metadata'],a.get('parent'),image_bytes(a.get('reference')))
        if op=='batch':return lib.batch(a['items'])
        if op=='validate':return lib.validate(a['version'],image_bytes(a.get('reference')))
        if op=='review':return lib.review(a['version'],a['decision'],a['note'])
        if op=='redraw_start':return lib.start_redraw(a['brief'],image_bytes(a.get('reference')))
        if op=='redraw_submit':return lib.submit_redraw(a['job'],a['svg'],a['metadata'])
        if op=='fragment':
            r=lib.row(a['version'])
            group=scene_group(json.loads(r['recipe']),a.get('box',[0,0,240,240]),a.get('prefix','icon'),a.get('color'),a.get('stroke_width'),a.get('points_per_unit',1))
            group['evidence']['note']+=' | PPTToolbox icon '+a['version']
            return {'version':a['version'],'metadata':json.loads(r['metadata']),'attribution':attribution(json.loads(r['metadata'])),'scene_fragment':group,
                    'usage':'提交到当前 region_objects 任务；必须保留来源并完成该项目的视觉检查'}
        if op=='place':return self.place(a)
        if op=='providers':
            import importlib.util
            config=self.manager.store.get('icon_model_provider',{})
            return {'host_agent':{'available':True,'mode':'Project-local native shapes/paths through region_objects; global-library redraw submissions are owner-only'},
                    'vtracer':{'available':importlib.util.find_spec('vtracer') is not None},
                    'svg_model':{'configured':bool(config.get('endpoint')),'name':config.get('name',''),'tested':False}}
        if op=='trace':
            raw=image_bytes(a['reference']);im=Image.open(io.BytesIO(raw)).convert('RGBA')
            import vtracer
            svg=vtracer.convert_pixels_to_svg(list(im.getdata()),im.size,colormode='color',hierarchical='stacked',mode='spline',filter_speckle=4,color_precision=6,layer_difference=16,corner_threshold=60,length_threshold=4,max_iterations=10,splice_threshold=45,path_precision=3)
            meta={**a['metadata'],'origin':'traced'}
            return lib.save(svg,meta,reference=raw)
        if op=='model_generate':return self.model_generate(a)

    def place(self,a):
        from ..policy import authorize, plain_path, PolicyDenied
        from ..workbench import Workbench
        m=self.manager
        if a.get('project_key'):
            project,_,_=Workbench(m).entry(a['project_key'])
        else:project=a['project']
        project,_=authorize(m,project)
        # Export is an immutable project asset; it never overwrites the active scene.
        if (project/'workflow/writer.lock').exists():raise PolicyDenied('项目正在写入，请稍后加入图标')
        row=self.library.row(a['version']);ir=json.loads(row['recipe'])
        options={k:a.get(k) for k in ('color','stroke_width')}
        key=digest(canonical({'format':3,'version':a['version'],'options':options}))
        target=plain_path(project/'assets'/'icons'/key)
        if not target.is_relative_to(project):raise PolicyDenied('图标目标超出项目')
        group=scene_group(ir,[12,12,216,216],'icon',a.get('color'),a.get('stroke_width'))
        group['evidence']['note']+=' | PPTToolbox icon '+a['version']
        manifest={'format':'icon-project-copy/2','version':a['version'],'options':options,'metadata':json.loads(row['metadata']),
                  'attribution':attribution(json.loads(row['metadata']))}
        if not target.exists():
            target.mkdir(parents=True)
            try:
                (target/'source.svg').write_text(row['source'],encoding='utf-8')
                (target/'ATTRIBUTION.txt').write_text(manifest['attribution']['text']+'\n',encoding='utf-8')
                (target/'icon.svg').write_text(svg_from_ir(ir,**{k:v for k,v in options.items() if v is not None}),encoding='utf-8')
                (target/'preview.png').write_bytes(render((target/'icon.svg').read_text(encoding='utf-8')))
                scene={'version':'1.0','canvas':{'width':240,'height':240,'width_pt':240,'height_pt':240,'mapping':'uniform'},'slides':[{'id':'icon-slide','objects':[group]}]}
                (target/'scene.json').write_text(canonical(scene),encoding='utf-8')
                # Existing compiler, including the same native path styles as Agent scenes.
                from scripts.runtime_env import child_environment
                import subprocess
                bootstrap="import sys,runpy;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')"
                result=subprocess.run([sys.executable,'-B','-c',bootstrap,str(m.root/'scripts'),str(m.root/'scripts/build_pptx.py'),str(target/'scene.json'),str(target/'icon.pptx')],capture_output=True,text=True,encoding='utf-8',env=child_environment(),timeout=60)
                if result.returncode:raise ValueError(result.stderr or result.stdout)
                manifest['files']={p.name:digest(p.read_bytes()) for p in target.iterdir() if p.is_file()}
                (target/'manifest.json').write_text(canonical(manifest),encoding='utf-8')
            except Exception:
                # Keep partial evidence; a later request must not accept it as complete.
                raise
        stored=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        expected={'source.svg','icon.svg','preview.png','scene.json','icon.pptx','icon.build.json','ATTRIBUTION.txt'}
        if set(stored.get('files',{}))!=expected:raise ValueError('项目图标副本清单无效')
        if stored.get('version')!=a['version'] or any(digest((target/name).read_bytes())!=h for name,h in stored['files'].items()):raise ValueError('项目图标副本不完整或已改变')
        return {'version':a['version'],'directory':str(target),'pptx':str(target/'icon.pptx'),'scene':str(target/'scene.json'),
                'scene_fragment':group,'manifest':stored,'scope':'已加入项目素材；Agent 在受管任务中放置到页面，未覆盖当前候选'}

    def model_generate(self,a):
        """Optional owner-configured local HTTP SVG provider, never a hidden download."""
        from urllib.parse import urlparse
        import urllib.request
        config=self.manager.store.get('icon_model_provider',{})
        endpoint=config.get('endpoint','');u=urlparse(endpoint)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:
            raise ValueError('请先在图标界面配置本机 SVG 模型服务')
        payload={'prompt':a['brief'],'reference':a.get('reference'),'format':'svg'}
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('模型服务不允许重定向')
        req=urllib.request.Request(endpoint,data=canonical(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(req,timeout=60) as response:raw=response.read(500001)
        if len(raw)>500000:raise ValueError('模型响应过大')
        result=json.loads(raw)
        return self.library.save(result['svg'],{**a['metadata'],'origin':'model'},reference=image_bytes(a.get('reference')))
