"""Authenticated loopback UI. No generic shell endpoint; ZIP import is data-only."""
from __future__ import annotations
import json,mimetypes,secrets,webbrowser,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs,quote
from .service import Manager
from .workbench import Workbench

WEB=Path(__file__).parent/'web'
PROMPT_READS={'prompt.read','prompt.history'}
PROMPT_WRITES={'prompt.save','prompt.restore','prompt.default'}
READS={'agent.live','learning.status','learning.source','agent.status','source','boot','tools','tool','packages','versions','settings','docs','doc','commands','logs','integration','startup-prompt'}
WRITES={'retrospective','learning.configure','learning.collect','learning.disable','agent.plan','agent.apply','agent.probe','agent.challenge','settings.save','storage.setup','storage.pick-directory','toggle','doc.save','command.save','doctor','diagnostic','package.commit','package.trust','package.activate','integration.export','integration.plan','integration.apply','config.export'}
READS |= {'experience.list','experience.show','experience.source'}
READS |= {'usage.summary','usage.detail'}
WRITES |= {'usage.record','usage.cite'}
READS |= PROMPT_READS
READS.add('agent.onboarding-prompt')
WRITES |= PROMPT_WRITES

class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,data_dir,port=0,token=None,**kw):
        self.manager=Manager(data_dir,**kw);self.token=token or secrets.token_urlsafe(32)
        self.workbench=Workbench(self.manager)
        self.write_lock=threading.RLock();self.closing=False
        super().__init__(('127.0.0.1',port),Handler);self.origin=f'http://127.0.0.1:{self.server_port}'
        from .pptagent import Worker
        from .project_hub import Observer
        self.manager.pptagent_worker=Worker(self.manager)
        self.manager.project_observer=Observer(self.manager)
        self.manager.pptagent_worker.start();self.manager.project_observer.start()
        from .software_updates import Updater
        self.updater=Updater(self.manager)
        self.updater.start()
    def server_close(self):
        self.updater.close()
        self.manager.project_observer.close();self.manager.pptagent_worker.close()
        super().server_close()
class Handler(BaseHTTPRequestHandler):
    server_version='PPTToolboxManager'
    def log_message(self,*args):pass
    def reply(self,data,status=200,mime='application/json; charset=utf-8',download=None):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        for k,v in {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cross-Origin-Resource-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(k,v)
        if download:self.send_header('Content-Disposition',"attachment; filename=export; filename*=UTF-8''"+quote(download))
        try:
            self.end_headers()
            self.wfile.write(data)
        except ConnectionError:
            # Navigating away cancels the directory's long-poll connection.
            # The response cannot be retried on that disconnected socket.
            pass
    def allowed(self,auth=False):
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':self.reply({'error':'Invalid Host'},403);return False
        if self.headers.get('Origin') and self.headers['Origin']!=self.server.origin:self.reply({'error':'Cross-origin request rejected'},403);return False
        if auth and not secrets.compare_digest(self.headers.get('Authorization','').removeprefix('Bearer '),self.server.token):self.reply({'error':'会话已失效，请从启动器重新打开管理界面'},401);return False
        return True
    def do_GET(self):
        u=urlparse(self.path);auth=u.path.startswith('/api/')
        if not self.allowed(auth):return
        try:
            a={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()}
            if u.path == '/api/software-update.status':
                self.reply({'ok':True,'result':self.server.updater.status()});return
            if u.path == '/api/projects.index':
                from .projects import directory
                previous=a.get('since'); deadline=time.monotonic()+min(25,max(0,float(a.get('wait',0))))
                while True:
                    result=directory(self.server.manager)
                    if result['revision']!=previous:
                        self.reply({'ok':True,'result':{**result,'changed':True}});return
                    if time.monotonic()>=deadline or self.server.closing:
                        self.reply({'ok':True,'result':{'revision':previous,'changed':False}});return
                    time.sleep(.5)
            if u.path in {'/api/project.activity','/api/project.simple-previews'}:
                from .project_hub import snapshot,previews
                self.reply({'ok':True,'result':(snapshot if u.path.endswith('.activity') else previews)(self.server.manager,a.get('project'))});return
            if u.path == '/api/project.simple-image':
                from .project_hub import entry,previews
                from scripts.project_journal import safe
                key=a.get('project'); name=a.get('path')
                if name not in {p for deck in previews(self.server.manager,key)['decks'] for p in deck['slides']}:
                    raise ValueError('预览已变化，请刷新')
                path=safe(entry(self.server.manager,key)[0],name)
                if path.stat().st_size>20_000_000:raise ValueError('预览图片过大')
                self.reply(path.read_bytes(),mime=mimetypes.guess_type(path.name)[0]);return
            if u.path == '/api/pptagent.settings':
                from .pptagent import config
                self.reply({'ok':True,'result':config(self.server.manager)});return
            if u.path == '/api/pptagent.tasks':
                from .pptagent_runtime import tasks
                self.reply({'ok':True,'result':tasks(self.server.manager)});return
            if u.path == '/api/projects.storage':
                from .project_inventory import overview
                self.reply({'ok':True,'result':overview(self.server.manager,a.get('refresh')=='1')});return
            if u.path == '/api/project.inventory':
                from .project_inventory import inspect
                self.reply({'ok':True,'result':inspect(self.server.manager,a.get('project'))});return
            if u.path == '/api/project.delivery-plan':
                from .project_lifecycle import delivery_plan
                self.reply({'ok':True,'result':delivery_plan(self.server.manager,a.get('project'))});return
            if u.path == '/api/material.policy':
                from .material_policy import effective
                root = self.server.workbench.entry(a['project'])[0] if a.get('project') else None
                self.reply({'ok':True,'result':effective(self.server.manager,root)});return
            if u.path in {'/api/project.gallery','/api/project.preview'}:
                from .project_gallery import gallery,image
                if u.path.endswith('.gallery'): self.reply({'ok':True,'result':gallery(self.server.manager,a.get('project'))})
                else: self.reply(image(self.server.manager,a.get('project'),a.get('path'),a.get('full')=='1'),mime='image/jpeg')
                return
            if u.path.startswith('/api/icons.'):
                from .icons.service import READS as ICON_READS
                op=u.path[len('/api/icons.'):]
                if op not in ICON_READS:raise ValueError('图标操作需要 POST')
                if 'include_drafts' in a:a['include_drafts']=a['include_drafts']=='true'
                if 'limit' in a:a['limit']=int(a['limit'])
                self.reply({'ok':True,'result':self.server.manager.icons(op,a,source='owner',project_scope=a.pop('tracking_project',None))});return
            if u.path.startswith('/api/graphics.'):
                op=u.path[len('/api/graphics.'):]
                if op not in {'inspect','validate'}:raise ValueError('Graphics operation requires POST')
                self.reply({'ok':True,'result':self.server.manager.graphics(op,a,source='owner',project_scope=a.pop('tracking_project',None))});return
            if u.path in {'/api/project.files','/api/project.file'}:
                from . import project_files
                if u.path.endswith('.files'):
                    self.reply({'ok':True,'result':project_files.listing(self.server.manager,a.get('project'),
                        group=a.get('group'),offset=int(a.get('offset',0)),limit=int(a.get('limit',100)))})
                else:
                    p=project_files.read(self.server.manager,a.get('project'),a.get('path'))
                    self.reply(p.read_bytes(),mime='application/octet-stream',download=p.name)
                return
            if u.path.startswith('/api/preparation.'):

                from . import preparation as prep
                op=u.path.split('.')[-1]
                if op=='list': result=list(prep.rows(self.server.manager).values())
                elif op=='get': result=prep.get(self.server.manager,a.get('id'))
                elif op=='prompt': result=prep.prompt(self.server.manager,a.get('id'))
                elif op=='image':
                    row=prep.get(self.server.manager,a.get('id'))
                    item=next((f for f in row['inputs'] if f['id']==a.get('file')),None)
                    if not item: raise ValueError('图片不存在')
                    self.reply(prep.input_file(row,item).read_bytes(),mime=item['mime']);return
                else: raise ValueError('准备任务操作不存在')
                self.reply({'ok':True,'result':result});return
            if u.path=='/api/projects.requests':
                from .requests import list_requests
                self.reply({'ok':True,'result':list_requests(self.server.manager)});return
            if u.path=='/api/workbench.projects':
                self.reply({'ok':True,'result':self.server.workbench.projects(summary=a.get('summary')=='1')});return
            if u.path=='/api/workbench.preferences':
                self.reply({'ok':True,'result':self.server.workbench.preferences()});return
            if u.path=='/api/workbench.snapshot':
                self.reply({'ok':True,'result':self.server.workbench.snapshot(a.get('project'),a.get('run'))});return
            if u.path=='/api/workbench.request':
                self.reply({'ok':True,'result':self.server.workbench.request(a.get('project'),a.get('id'))});return
            if u.path=='/api/workbench.artifact':
                self.reply(self.server.workbench.artifact(a.get('project'),a.get('id')),mime='image/png');return
            if u.path=='/api/file':
                p=self.server.manager.export_file(a.get('id',''));self.reply(p.read_bytes(),mime='application/octet-stream',download=p.name);return
            if auth:
                op=u.path[5:]
                if op not in READS:self.reply({'error':'Not found'},404);return
                self.reply({'ok':True,'result':self.server.manager.call(op,a)});return
            p=(WEB/(u.path.lstrip('/') or 'index.html')).resolve()
            if not p.is_relative_to(WEB.resolve()) or not p.is_file():self.reply({'error':'Not found'},404);return
            mime=mimetypes.guess_type(p.name)[0] or 'text/plain'
            if p.suffix in {'.js','.css','.html'}:mime+='; charset=utf-8'
            self.reply(p.read_bytes(),mime=mime)
        except Exception as e:self.reply({'ok':False,'error':str(e)},400)
    def do_POST(self):
        with self.server.write_lock:
            if self.server.closing:
                self.reply({'error':'Desktop is stopping; no new UI writes accepted'},503);return
            self.post()
    def post(self):
        if not self.allowed(True):return
        try:
            n=int(self.headers.get('Content-Length',0));u=urlparse(self.path)
            if n<=0 or n>32*1024*1024:raise ValueError('请求超过 32MB 或为空')
            raw=self.rfile.read(n)
            if u.path=='/api/package.inspect':
                if self.headers.get_content_type()!='application/octet-stream':raise ValueError('需要ZIP二进制数据')
                result=self.server.manager.prepare_import(raw)
            else:
                limit=29_000_000 if u.path=='/api/preparation.upload' else 18_000_000 if u.path.startswith('/api/graphics.') else 10_000_000 if u.path.startswith('/api/icons.') else 512000
                if n>limit or self.headers.get_content_type()!='application/json':raise ValueError('JSON 请求过大或内容类型不正确')
                if u.path.startswith('/api/software-update.'):
                    op=u.path.removeprefix('/api/software-update.')
                    if op not in {'check','download','cancel','install','configure'}:
                        raise ValueError('更新操作不存在')
                    body=json.loads(raw)
                    if not isinstance(body,dict) or (op!='configure' and body):
                        raise ValueError('更新操作不接受额外参数')
                    handler=getattr(self.server.updater,op)
                    result=handler(body) if op=='configure' else handler()
                    self.reply({'ok':True,'result':result});return
                if u.path in {'/api/project.create-folder','/api/project.scan'}:
                    from .project_hub import create,scan
                    body=json.loads(raw)
                    self.reply({'ok':True,'result':create(self.server.manager,body) if u.path.endswith('create-folder') else scan(self.server.manager)});return
                if u.path == '/api/pptagent.settings.save':
                    from .pptagent import save_config
                    self.reply({'ok':True,'result':save_config(self.server.manager,json.loads(raw))});return
                if u.path in {'/api/pptagent.test','/api/pptagent.run','/api/pptagent.cancel'}:
                    from .pptagent_runtime import submit,cancel
                    body=json.loads(raw)
                    result=cancel(self.server.manager,body) if u.path.endswith('.cancel') else submit(self.server.manager,body,probe=u.path.endswith('.test'))
                    self.reply({'ok':True,'result':result});return
                if u.path == '/api/project.issue.acknowledge':
                    from .project_hub import acknowledge_issue
                    self.reply({'ok':True,'result':acknowledge_issue(self.server.manager,json.loads(raw))});return
                if u.path == '/api/project.notes.save':
                    from .project_hub import entry
                    from scripts.project_journal import save_notes
                    body=json.loads(raw);root=entry(self.server.manager,body.get('project'))[0]
                    self.reply({'ok':True,'result':save_notes(root,body.get('text'),body.get('revision'))});return
                if u.path.startswith('/api/preparation.'):
                    from . import preparation as prep
                    body=json.loads(raw);op=u.path.split('.')[-1]
                    if op not in {'create','upload','update','export'}: raise ValueError('准备任务操作不存在')
                    result=getattr(prep,op)(self.server.manager,body.get('id') if op=='export' else body)
                    self.reply({'ok':True,'result':result});return
                if u.path == '/api/material.policy.save':
                    from .material_policy import save_project
                    self.reply({'ok':True,'result':save_project(self.server.manager,json.loads(raw))});return
                if u.path == '/api/project.open':
                    from .project_files import open_local
                    self.reply({'ok':True,'result':open_local(self.server.manager,json.loads(raw))});return
                if u.path == '/api/storage.open':
                    from .project_inventory import open_global
                    self.reply({'ok':True,'result':open_global(self.server.manager,json.loads(raw))});return
                if u.path in {'/api/project.complete','/api/project.reopen','/api/project.cleanup-preview','/api/project.cleanup'}:
                    from . import project_lifecycle
                    operation={'/api/project.complete':project_lifecycle.complete,
                               '/api/project.reopen':project_lifecycle.reopen,
                               '/api/project.cleanup-preview':project_lifecycle.preview_cleanup,
                               '/api/project.cleanup':project_lifecycle.cleanup}[u.path]
                    body=json.loads(raw)
                    result=operation(self.server.manager,body)
                    from .projects import cache_summary
                    cache_summary(self.server.manager,body.get('project'))
                    self.reply({'ok':True,'result':result});return
                if u.path=='/api/icon-provider.save':
                    body=json.loads(raw);endpoint=body.get('endpoint','');parsed=urlparse(endpoint)
                    if endpoint and (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'} or parsed.username or parsed.password):raise ValueError('只支持本机 HTTP 模型服务')
                    self.server.manager.store.set('icon_model_provider',{'endpoint':endpoint,'name':str(body.get('name',''))[:100]})
                    self.reply({'ok':True,'result':{'configured':bool(endpoint)}});return
                if u.path.startswith('/api/icons.'):
                    body=json.loads(raw); scope=body.pop('tracking_project',None)
                    self.reply({'ok':True,'result':self.server.manager.icons(u.path[len('/api/icons.'):],body,source='owner',project_scope=scope)});return
                if u.path.startswith('/api/graphics.'):
                    body=json.loads(raw); scope=body.pop('tracking_project',None)
                    self.reply({'ok':True,'result':self.server.manager.graphics(u.path[len('/api/graphics.'):],body,source='owner',project_scope=scope)});return
                if u.path=='/api/workbench.edit':
                    self.reply({'ok':True,'result':self.server.workbench.write(json.loads(raw))});return
                if u.path=='/api/workbench.preferences.save':
                    self.reply({'ok':True,'result':self.server.workbench.save_preferences(json.loads(raw))});return
                if u.path=='/api/projects.update':
                    from .projects import update_metadata
                    self.reply({'ok':True,'result':update_metadata(self.server.manager,json.loads(raw))});return
                if u.path=='/api/projects.reorder':
                    from .projects import reorder
                    self.reply({'ok':True,'result':reorder(self.server.manager,json.loads(raw))});return
                if u.path=='/api/projects.request-decision':
                    from .requests import decide
                    self.reply({'ok':True,'result':decide(self.server.manager,json.loads(raw))});return
                if u.path=='/api/projects.request-archive':
                    from .requests import archive_request
                    self.reply({'ok':True,'result':archive_request(self.server.manager,json.loads(raw))});return
                if not u.path.startswith('/api/') or u.path[5:] not in WRITES:raise ValueError('操作不允许从浏览器执行')
                result=self.server.manager.call(u.path[5:],json.loads(raw))
            self.reply({'ok':True,'result':result})
        except Exception as e:self.reply({'ok':False,'error':str(e)},400)
    def do_OPTIONS(self):self.reply({'error':'Cross-origin access disabled'},403)

def serve(data_dir,port=0,open_browser=True):
    server=LocalServer(data_dir,port);url=server.origin+'/#token='+server.token
    from . import VERSION
    version=(server.manager.distribution() or {}).get('version') or VERSION
    print('PPT 工具箱 '+version+'\n管理数据 '+str(server.manager.data)+'\n打开地址 '+url+'\n仅本机访问。关闭服务请按 Ctrl+C。',flush=True)
    if open_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
