"""Management service. No slide canvas, project builder or auto-generated content.
UI, managed CLI and MCP share package settings and execution authorization.
"""
from __future__ import annotations
import difflib,importlib.util,io,json,os,re,secrets,shutil,subprocess,sys,tempfile,threading,zipfile
from pathlib import Path
from . import VERSION, API_VERSION
from .storage import Store,stamp,digest,redact
from .packages import inspect_zip,tree_hashes,safe_name,installed_compatibility
from scripts.runtime_env import powershell_path, child_environment, python_tool_argv
from scripts.release_info import read_release

ROOT=Path(__file__).resolve().parents[1]
WORKFLOWS={'start':'建立制作任务','next':'领取当前任务','status':'读取任务状态','advance':'推进已就绪步骤','finish':'核查并交付','handoff':'生成续作交接','submit':'提交任务结果','review-again':'重新审查','retry':'重试失败步骤','revise':'限定区域返修','replace-candidate':'替换候选PPTX','replace-scene':'替换对象清单','asset-add':'登记素材','unlock':'核对并解除任务锁','preview':'LibreOffice独立预审（Office仍待验证）'}
DEFAULTS={'revision':0,'theme':'light','python_path':'','powershell_path':'','agent_execution_enabled':False,
    'auto_approve_project_requests':False,'material_search_allowed':True,'reference_upload_allowed':True,
    'network_benchmarks_enabled':False,'host_generation_allowed':True,'log_page_size':100,'update_channel':'stable',
    'projects_directory':'','major_stage_checkpoints':True}
LABELS={'python':'Python 脚本','powershell':'PowerShell 脚本','powershell_module':'PPT 原生指令','host':'宿主能力','manual':'操作手册'}

class Manager:
    def __init__(self,data_dir,root=ROOT,home=None):
        self.root=Path(root).resolve()
        from .instance import check_retired
        check_retired(data_dir)
        if Path(data_dir).expanduser().resolve().is_relative_to(self.root):raise ValueError('管理数据目录必须位于程序包之外，避免更新覆盖与打包污染')
        self.store=Store(data_dir);self.data=self.store.root;self.home=Path(home or Path.home()).resolve()
        self.lock=threading.RLock();self.pending={}
        # Built-in code is the application the user explicitly launched; imported code starts untrusted.
        if not self.store.get('initialized'):
            txt=(self.root/'SKILL.md').read_text(encoding='utf-8');v=re.search(r'version:\s*"([^\"]+)"',txt)
            ver=read_release(self.root)['version'] if (self.root/'release.json').is_file() else (v[1] if v else 'unknown')
            with self.store.db() as c:
                c.execute('INSERT OR IGNORE INTO packages VALUES(?,?,?,?,?,?,?,?,?,?)',('builtin','ppt-reference-rebuild',ver,'设计图片到可编辑 PPT 的完整 Skill 与工具箱',str(self.root),'builtin','bundled',1,1,stamp()))
            self.store.set('active_package','builtin')
            settings=self.store.get('settings')
            if settings is None:
                settings=dict(DEFAULTS)
                try:
                    from .policy import plain_path
                    location=json.loads(plain_path(self.root.parent/'location.json').read_text(encoding='utf-8-sig'))
                    if isinstance(location,dict):
                        data=location.get('data_directory')
                        if isinstance(data,str) and Path(data).is_absolute() and plain_path(data)==self.data:
                            settings['projects_directory']=self._projects_directory(location.get('projects_directory'))
                except (OSError,ValueError):
                    # Invalid installer metadata cannot grant paths or prevent startup.
                    pass
            self.store.set('settings',settings);self.store.set('initialized',True)
            self.store.event('manager.initialized','已登记随包 Skill；没有扫描或修改其他 Agent 配置。')
        # Relocating the extracted bundle updates its source location, not the user's project paths.
        txt=(self.root/'SKILL.md').read_text(encoding='utf-8');match=re.search(r'version:\s*"([^\"]+)"',txt)
        current_version=read_release(self.root)['version'] if (self.root/'release.json').is_file() else (match[1] if match else 'unknown')
        with self.store.db() as c:
            old=c.execute('SELECT version FROM packages WHERE id="builtin"').fetchone()
            c.execute('UPDATE packages SET path=?,version=? WHERE id="builtin"',(str(self.root),current_version))
        if old and old['version']!=current_version:
            self.store.event('builtin.version_changed','内置制作工具已随软件更新；用户指令覆盖保留。',details={'old':old['version'],'new':current_version})
        from .releases import observe
        observe(self.store,self.distribution())
    def package(self,pid=None):
        pid=pid or self.store.get('active_package','builtin')
        with self.store.db() as c:r=c.execute('SELECT * FROM packages WHERE id=?',(pid,)).fetchone()
        if not r:raise ValueError('工具包不存在')
        return {**dict(r),'enabled':bool(r['enabled']),'trusted':bool(r['trusted'])}
    def packages(self):
        active=self.store.get('active_package')
        with self.store.db() as c:rows=c.execute('SELECT * FROM packages ORDER BY created DESC').fetchall()
        return [{**dict(r),'enabled':bool(r['enabled']),'trusted':bool(r['trusted']),'active':r['id']==active,
                 'compatibility':installed_compatibility(r['path']) if r['source']=='imported' else {'status':'bundled','message':'随软件更新'}} for r in rows]
    def settings(self):return {k:v for k,v in {**DEFAULTS,**self.store.get('settings',{})}.items() if k in DEFAULTS}
    def _projects_directory(self,value,field='projects_directory'):
        from .policy import plain_path
        if not isinstance(value,str) or len(value)>8000 or any(ord(c)<32 for c in value):
            raise ValueError(field+' must be an absolute existing directory or empty')
        if not value:return ''
        if not Path(value).is_absolute():
            raise ValueError(field+' must be absolute')
        directory=plain_path(value)
        if not directory.is_dir():
            raise ValueError(field+' must be an existing directory')
        protected=[plain_path(p) for p in (self.root,self.package()['path'],self.data)]
        if any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in protected):
            raise ValueError(field+' must be separate from package and management data')
        return str(directory)
    def save_settings(self,body):
        expected=body.get('revision');values=body.get('values')
        if not isinstance(values,dict) or values.keys()-(DEFAULTS.keys()-{'revision'}):raise ValueError('未知设置字段')
        for k,v in values.items():
            if isinstance(DEFAULTS[k],bool) and type(v) is not bool:raise ValueError(k+' 需要布尔值')
        if values.get('theme','light') not in {'light','dark'}:raise ValueError('主题不支持')
        if values.get('update_channel','stable') not in {'stable','offline'}:raise ValueError('更新渠道无效')
        if 'log_page_size' in values and (type(values['log_page_size']) is not int or not 20<=values['log_page_size']<=1000):raise ValueError('日志每页数量需为 20–1000')
        for k in ['python_path','powershell_path']:
            if k in values and (not isinstance(values[k],str) or len(values[k])>500 or any(x in values[k] for x in ['\n','\x00'])):raise ValueError('可执行文件路径非法')
        values=dict(values)
        if 'projects_directory' in values:values['projects_directory']=self._projects_directory(values['projects_directory'])
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT value FROM kv WHERE key="settings"').fetchone();current=json.loads(r[0])
            if expected!=current['revision']:raise ValueError('设置已被另一窗口修改，请刷新后重试')
            merged={**current,**values,'revision':current['revision']+1}
            c.execute('UPDATE kv SET value=? WHERE key="settings"',(json.dumps(merged,ensure_ascii=False),))
        self.store.event('settings.saved','已保存管理器设置',details={'changed_fields':list(values)})
        return self.settings()
    def override(self,pid,kind,target,default=None):
        with self.store.db() as c:r=c.execute('SELECT value FROM overrides WHERE package_id=? AND kind=? AND target=?',(pid,kind,target)).fetchone()
        return json.loads(r[0]) if r else default
    def toggle(self,kind,target,enabled,pid=None):
        if type(enabled) is not bool:raise ValueError('enabled 需要布尔值')
        p=self.package(pid)
        if kind=='package':
            with self.store.db() as c:c.execute('UPDATE packages SET enabled=? WHERE id=?',(int(enabled),p['id']))
        elif kind=='tool':
            if target not in {r['id'] for r in self.catalog(p['id'])}:raise ValueError('工具不存在')
            with self.store.db() as c:c.execute('INSERT INTO overrides VALUES(?,?,?,?) ON CONFLICT(package_id,kind,target) DO UPDATE SET value=excluded.value',(p['id'],'tool',target,json.dumps(enabled)))
        else:raise ValueError('不支持的启停类型')
        self.store.event(kind+'.toggled',('启用' if enabled else '停用')+' '+(target or p['name']),details={'package_id':p['id'],'scope':'managed_dispatch_only'})
        return {'enabled':enabled,'scope':'仅管理器与受管 CLI / MCP；不修改既有 Codex 配置，也不限制直接运行原脚本。'}
    def catalog(self,pid=None):
        from .contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
        p=self.package(pid);path=Path(p['path'])/'toolbox/registry.json'
        if not path.exists():return []
        rows=json.loads(path.read_text(encoding='utf-8'))['tools'];out=[]
        if p['name']=='ppt-reference-rebuild' and (Path(p['path'])/'toolbox.py').is_file():
            rows += [{'id':'workflow.'+cmd,'title':title,'kind':'python','entry':'toolbox.py','prefix':[cmd],
                      'inputs':cmd+' --project <project> [按 --help 填写所需参数]','outputs':'真实任务状态与下一步，不自动认定视觉通过',
                      'manuals':['references/workflow-protocol.md','references/managed-execution.md'],'limitations':'受管工作流在副作用前检查内部能力并关联运行证据；不限制绕过管理器直接执行脚本。'} for cmd,title in {**WORKFLOWS, **{n:'局部重建 '+n for n in (*LOCAL_COMMANDS,*REQUEST_COMMANDS)}}.items()]
        if p['name']=='ppt-reference-rebuild':
            from .icons.contracts import SPECS
            rows += [{'id':'icons.'+op,'title':description,'kind':'python','entry':'manager.py',
                      'inputs':'--json <JSON file>','outputs':'图标版本、配方及验证证据',
                      'manuals':['references/icon-library.md'],'limitations':'遵循受管执行与项目授权；自绘草稿不能自动认定视觉通过'} for op,(description,_) in SPECS.items()]
            from .graphics import SPECS as GRAPHICS
            rows += [{'id':'graphics.'+op,'title':description,'kind':'python','entry':'manager.py',
                      'inputs':'--json <request.json>','outputs':'Native graphics drafts and evidence',
                      'manuals':['references/graphics-construction.md'],
                      'limitations':'Authorized project assets only; no automatic adoption or visual approval.'}
                     for op,(description,_) in GRAPHICS.items()
                     if 'graphics.'+op not in {row['id'] for row in rows}]
        # One fresh snapshot per catalog request; never cache permission switches
        # across requests. Per-tool SQLite connections dominated task dispatch.
        with self.store.db() as c:
            overrides={r['target']:json.loads(r['value']) for r in c.execute(
                'SELECT target,value FROM overrides WHERE package_id=? AND kind=?',
                (p['id'],'tool')).fetchall()}
        for row in rows:
            exists=bool(row.get('entry') and (Path(p['path'])/row['entry']).is_file())
            availability='宿主发现后可用' if row['kind']=='host' else '文件缺失' if not exists else '需 Windows / Office 实测' if row['kind'].startswith('powershell') else '已收录，依赖另检' if row['kind']=='python' else '可阅读'
            out.append({**row,'kind_label':LABELS.get(row['kind'],row['kind']),'enabled':overrides.get(row['id'],True),
                'package_id':p['id'],'availability':availability,'local_entry':str(Path(p['path'])/row['entry']) if row.get('entry') else None})
        return out
    def tool(self,tid):
        if tid.startswith("native."):
            return self.native_card(tid[len("native."):])
        r=next((r for r in self.catalog() if r['id']==tid),None)
        if r is None:raise ValueError('工具不存在')
        p=self.package();py=sys.executable
        args=[py,str(self.root/'manager.py'),'--data-dir',str(self.data),'execute','--tool',tid,'--']
        # JSON argv is canonical; platform-specific shell string is informational only.
        return {**r,'managed_argv_prefix':args,'powershell_example':'& '+ ' '.join("'"+a.replace("'","''")+"'" for a in args)+' <参数>',
            'note':'指令示例仅供复制；浏览器不执行任意工具参数。运行须开启受管执行，且工具包已信任。'}
    def native_card(self, cid):
        from scripts.native_capabilities import card
        from .native_evidence import lookup
        r = card(cid)
        enabled = {v["id"]: v["enabled"] for v in self.catalog()}
        needed = ("workflow.patch", "ops.patch-pptx", "pptx.validate", "pptx.build",
                  "pptx.inspect", "office.render", "office.edit-readback")
        if cid.startswith("recipe."):
            needed = ("workflow.probe", "ops.component", "pptx.build", "pptx.validate",
                      "pptx.inspect", "office.render", "assets.crop")
        usable = r["callable"] and self.package()["enabled"] and self.package()["trusted"] and all(enabled.get(k, False) for k in needed)
        return {**r, "id": "native."+cid, "enabled": bool(usable),
                "callable": bool(usable), "execution_enabled": self.settings()["agent_execution_enabled"],
                "local_evidence": lookup(self, cid),
                "required_tools": list(needed), "manual_path": "native/"+cid,
                "entry_note": ("Use discovered rebuild_probe schema with result.components; "
                               if cid.startswith("recipe.") else
                               "Use discovered rebuild_patch schema with "+r.get("operation","its registered operation")+"; ")
                              + "owner project authorization remains required."}
    def search(self, query):
        from scripts.native_capabilities import search
        native = [self.native_card(r["capability_id"]) for r in search(query)]
        q = query.casefold()
        old = [r for r in self.catalog() if r["enabled"] and q in json.dumps(r,ensure_ascii=False).casefold()]
        return native + old[:max(0, 8-len(native))] if native else old
    def source(self,tid):
        tool=self.tool(tid)
        if not tool.get('entry'):raise ValueError('宿主能力没有本地源代码')
        root=Path(self.package()['path']).resolve();path=(root/tool['entry']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix not in {'.py','.ps1','.psm1','.json','.md'}:
            raise ValueError('源文件不在可读范围')
        raw=path.read_bytes()
        return {'entry':tool['entry'],'content':raw[:200000].decode('utf-8-sig',errors='replace'),'truncated':len(raw)>200000,'scope':'只读源代码，不执行。修改核心代码请在独立版本中进行并重新打包。'}
    def docs(self,pid=None):
        p=self.package(pid);root=Path(p['path']);files=[]
        for q in [root/'SKILL.md',root/'README.md',root/'给模型的启动指令.txt',*sorted((root/'manager_docs').glob('*.md')),root/'toolbox/README.md',root/'toolbox/COMMANDS.md',*sorted((root/'references').glob('*.md'))]:
            if q.is_file() and not q.is_symlink():
                rel=q.relative_to(root).as_posix();text=q.read_text(encoding='utf-8-sig')
                title=next((line.lstrip('# ').strip() for line in text.splitlines() if line.startswith('# ')),q.stem)
                with self.store.db() as c:r=c.execute('SELECT revision FROM docs WHERE package_id=? AND path=?',(p['id'],rel)).fetchone()
                files.append({'path':rel,'title':title,'customized':bool(r),'editable':rel in {'SKILL.md','给模型的启动指令.txt'} or rel.startswith('references/'),'revision':r[0] if r else 0})
        return files
    def document(self,path,pid=None):
        p=self.package(pid);entry=next((d for d in self.docs(p['id']) if d['path']==path),None)
        if not entry:raise ValueError('文档不在允许读取列表中')
        base=(Path(p['path'])/path).read_text(encoding='utf-8-sig')
        with self.store.db() as c:
            row=c.execute('SELECT * FROM docs WHERE package_id=? AND path=?',(p['id'],path)).fetchone()
            hist=c.execute('SELECT revision,updated FROM doc_history WHERE package_id=? AND path=? ORDER BY id DESC LIMIT 30',(p['id'],path)).fetchall()
        base_hash=digest(base)
        acknowledged=self.store.get('doc-base:'+p['id']+':'+path)
        return {**entry,'package_id':p['id'],'base':base,'base_sha256':base_hash,'base_changed':bool(row) and acknowledged!=base_hash,'content':row['content'] if row else base,'revision':row['revision'] if row else 0,
            'history':[dict(x) for x in hist],'diff':'\n'.join(difflib.unified_diff(base.splitlines(),(row['content'] if row else base).splitlines(),fromfile='随包版本',tofile='用户覆盖',lineterm=''))}
    def save_document(self,path,content,revision,pid=None,restore_revision=None):
        p=self.package(pid);doc=self.document(path,p['id'])
        if not doc['editable']:raise ValueError('该文档只读；可在指令库创建自定义指令')
        if restore_revision is not None:
            if restore_revision==0:content=doc['base']
            else:
                with self.store.db() as c:r=c.execute('SELECT content FROM doc_history WHERE package_id=? AND path=? AND revision=? ORDER BY id DESC LIMIT 1',(p['id'],path,restore_revision)).fetchone()
                if not r:raise ValueError('历史版本不存在')
                content=r[0]
        if not isinstance(content,str) or len(content.encode())>250000:raise ValueError('文本过长或格式错误')
        if path=='SKILL.md' and not content.startswith('---'):raise ValueError('保留 Skill 的 YAML front matter')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT content,revision FROM docs WHERE package_id=? AND path=?',(p['id'],path)).fetchone()
            current=r['revision'] if r else 0
            if revision!=current:raise ValueError('指令已被另一窗口修改，请刷新后重试')
            old=r['content'] if r else doc['base']
            c.execute('INSERT INTO doc_history(package_id,path,content,revision,updated) VALUES(?,?,?,?,?)',(p['id'],path,old,current,stamp()))
            c.execute('INSERT INTO docs VALUES(?,?,?,?,?) ON CONFLICT(package_id,path) DO UPDATE SET content=excluded.content,revision=excluded.revision,updated=excluded.updated',(p['id'],path,content,current+1,stamp()))
        self.store.set('doc-base:'+p['id']+':'+path,digest(doc['base']))
        self.store.event('instruction.saved','保存用户指令覆盖 '+path,details={'package':p['id'],'revision':current+1})
        return self.document(path,p['id'])
    def commands(self):
        with self.store.db() as c:
            saved=[dict(r) for r in c.execute('SELECT * FROM commands ORDER BY updated DESC').fetchall()]
        # Built-in templates are readable without a database migration. Explicit
        # edits, including disabled commands, always win over bundled defaults.
        package=self.package()
        path=self.root/'assets/experience/knowledge/command-recipes.json'
        if package['id']!='builtin' or not package['enabled'] or not package['trusted'] or not path.is_file():
            return saved
        known={row['id'] for row in saved}
        defaults=json.loads(path.read_text(encoding='utf-8')).get('commands',[])
        return saved+[{**{k:row[k] for k in ('id','title','description','body')},
                       'enabled':1,'revision':0,'updated':'','builtin':True}
                      for row in defaults if row['id'] not in known]
    def save_command(self,b):
        tid=b.get('id') or 'cmd-'+secrets.token_hex(5);title=b.get('title','');body=b.get('body','')
        if not re.fullmatch('[a-zA-Z0-9_-]{1,70}',tid) or not 1<=len(title)<=100 or not isinstance(body,str) or not 1<=len(body)<=30000:raise ValueError('指令名称或内容不合法')
        if len(b.get('description',''))>2000:raise ValueError('说明过长')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT revision FROM commands WHERE id=?',(tid,)).fetchone();rev=r[0] if r else 0
            if b.get('revision',0)!=rev:raise ValueError('指令版本冲突，请刷新')
            c.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,body=excluded.body,enabled=excluded.enabled,revision=excluded.revision,updated=excluded.updated',
                (tid,title,b.get('description',''),body,int(b.get('enabled',True)),rev+1,stamp()))
        self.store.event('command.saved','保存指令 '+title)
        return {'id':tid,'revision':rev+1}
    def boot(self):
        from .project_context import toolbox_locations
        packages=self.packages();tools=self.catalog();settings=self.settings()
        with self.store.db() as c:custom=c.execute('SELECT count(*) FROM docs').fetchone()[0];count=c.execute('SELECT count(*) FROM events').fetchone()[0]
        return {'name':'PPT Toolbox','version':VERSION,'api_version':API_VERSION,'active':self.package(),'packages':packages,'settings':settings,
            'counts':{'packages':len(packages),'tools':len(tools),'enabled_tools':sum(t['enabled'] for t in tools),'custom_docs':custom,'events':count},
            'data_dir':str(self.data),'app_dir':str(self.root),'storage':toolbox_locations(self),'python':sys.executable,'platform':sys.platform,
            'limits':['此界面管理能力与配置，不承担 PPT 页面制作。','本机启停仅约束受管入口，不是操作系统安全隔离。','日志包含管理操作和受管调用；不会自动读取 Codex 全部历史。'],
            'registration':self.store.get('registration'),'distribution':self.distribution(),'instance':self.instance()}
    def instance(self):
        from .instance import describe
        return describe(self)
    def open_setup(self):
        launcher = self.root.parent/'PPTToolbox.exe'
        if not (self.root/'PRODUCT.json').is_file() or not launcher.is_file():
            raise ValueError('Installation and migration require the packaged application')
        subprocess.Popen([str(launcher),'--setup','--data-dir',str(self.data)],
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
        self.store.event('storage.setup','Owner opened installation and migration wizard',source='owner')
        return {'opened':True,'migration_started':False}
    def distribution(self):
        path=self.root/'PRODUCT.json'
        if not path.is_file():return None
        value=json.loads(path.read_text(encoding='utf-8'))
        return {key:value[key] for key in ('product','version','source_sha256','manager_version',
                'core_version','mcp_tool_count','mcp_tool_names') if key in value}
    def doctor(self):
        p=self.package();settings=self.settings();modules={x:bool(importlib.util.find_spec(x)) for x in ['PIL','numpy','pptx','lxml','jsonschema','shapely']}
        try:
            selected_shell=powershell_path(settings['powershell_path'])
            shell_check={'name':'PowerShell','status':'detected' if selected_shell else 'missing','detail':selected_shell or '未发现；可在设置中指定'}
        except FileNotFoundError as exc:
            shell_check={'name':'PowerShell','status':'missing','detail':str(exc)}
        checks=[{'name':'管理器 Python','status':'passed','detail':sys.version.split()[0]+' · '+sys.executable},
          {'name':'本地配置存储','status':'passed','detail':str(self.store.path)},
          {'name':'PPT 核心依赖（当前解释器）','status':'passed' if all(modules[x] for x in ['PIL','numpy','pptx','lxml','jsonschema']) else 'missing','detail':', '.join(k+(' ✓' if v else ' 缺失') for k,v in modules.items())},
          shell_check,
          {'name':'PowerPoint COM','status':'not_run','detail':'需要 Windows 桌面 Office 实测；本检查不会启动或关闭 Office'},
          {'name':'Codex CLI','status':'detected' if shutil.which('codex') else 'missing','detail':shutil.which('codex') or '未在 PATH 发现'},
          {'name':'宿主生图','status':'not_run','detail':'由 Codex 等宿主发现并调用，管理器不代理模型或保存密钥'}]
        if settings['python_path']:checks.append({'name':'指定的核心 Python','status':'detected' if Path(settings['python_path']).is_file() else 'missing','detail':settings['python_path']+'；其依赖未自动验证'})
        result={'checks':checks,'scope':'文件与当前解释器能力探测；不是 Office、模型或插件宿主实测。','time':stamp()}
        self.store.set('last_doctor',result);self.store.event('environment.checked','完成环境检测；Office 与宿主生图仍需实测')
        return result
    def diagnostic(self,kind):
        p=self.package()
        if not p['enabled'] or not p['trusted']:raise ValueError('先启用并确认信任此工具包，再运行代码诊断')
        commands={'registry':['tools','check'],'components':['ops','components'],'doctor':['doctor']}
        if kind not in commands:raise ValueError('诊断操作不在白名单')
        entry=Path(p['path'])/'toolbox.py'
        if not entry.is_file():raise ValueError('此包没有 toolbox.py；只支持文档管理')
        py=self.settings()['python_path'] or sys.executable
        try:
            r=subprocess.run([py,str(entry),*commands[kind]],capture_output=True,timeout=45,text=True,encoding='utf-8',errors='replace',shell=False,env=child_environment(self.settings()['powershell_path']))
            out={'returncode':r.returncode,'stdout':redact(r.stdout[-40000:]),'stderr':redact(r.stderr[-10000:]),'status':'passed' if r.returncode==0 else 'failed'}
        except (OSError,subprocess.TimeoutExpired) as e:out={'status':'failed','error':redact(str(e))}
        self.store.event('diagnostic.'+kind,'运行工具包诊断 '+kind,status='ok' if out['status']=='passed' else 'error',details=out)
        return out
    def prepare_import(self,data):
        info=inspect_zip(data);old=self.package()
        # Development release archives and validation backups are not the active
        # built-in package. Imported package integrity still hashes its full tree.
        excluded={'dist','checks','.tmp','.local-backups','.playwright-cli'} if old['id']=='builtin' else set()
        oldfiles=tree_hashes(old['path'],exclude_root=excluded);newfiles={n:digest(b) for n,b in info['files'].items()}
        pid=info['name']+'@'+info['version']+'-'+info['fingerprint'][:10]
        token=secrets.token_urlsafe(24);self.pending[token]=info
        changes={'added':sorted(newfiles.keys()-oldfiles.keys()),'removed':sorted(oldfiles.keys()-newfiles.keys()),'changed':sorted(n for n in newfiles.keys()&oldfiles.keys() if newfiles[n]!=oldfiles[n])}
        self.store.event('package.inspected','已检查离线包 '+info['name']+' '+info['version'],details={'integrity':info['integrity'],'file_count':info['file_count']})
        return {k:v for k,v in info.items() if k!='files'}|{'id':pid,'confirm_id':token,'changes':changes,'base_package':old['id'],
            'warning':'哈希只验证完整性，不证明发布者身份。导入后默认停用、不信任，不执行代码、钩子或依赖安装。'}
    def commit_import(self,confirm_id):
        with self.lock:
            info=self.pending.pop(confirm_id,None)
            if not info:raise ValueError('检查结果已失效，请重新选择 ZIP')
            if info['compatibility']['status']=='incompatible':raise ValueError(info['compatibility']['message'])
            pid=info['name']+'@'+info['version']+'-'+info['fingerprint'][:10]
            dest=self.data/'packages'/pid
            with self.store.db() as c:
                if c.execute('SELECT 1 FROM packages WHERE id=?',(pid,)).fetchone():raise ValueError('相同版本与内容已经导入')
            if dest.exists():raise ValueError('安装目录已存在，请检查后重试')
            dest.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=dest.parent,prefix='stage-') as tmp:
                t=Path(tmp)/'package';t.mkdir()
                for rel,blob in info['files'].items():
                    q=t/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(blob)
                t.rename(dest)
            with self.store.db() as c:c.execute('INSERT INTO packages VALUES(?,?,?,?,?,?,?,?,?,?)',
                (pid,info['name'],info['version'],info['description'],str(dest),'imported',info['fingerprint'],0,0,stamp()))
            self.store.event('package.imported','已导入 '+info['name']+' '+info['version']+'；未启用、未执行')
            return self.package(pid)
    def trust(self,pid,acknowledge=False):
        if acknowledge is not True:raise ValueError('需要明确确认已审阅来源；信任后包中的代码可由受管入口运行')
        self.package(pid)
        with self.store.db() as c:c.execute('UPDATE packages SET trusted=1 WHERE id=?',(pid,))
        self.store.event('package.trusted','用户确认信任工具包',details={'id':pid})
        return self.package(pid)
    def activate(self,pid):
        p=self.package(pid)
        if not p['trusted'] or not p['enabled']:raise ValueError('切换前需明确启用并确认信任')
        if p['source']=='imported':
            actual=digest(json.dumps(tree_hashes(p['path']),sort_keys=True))
            if actual!=p['fingerprint']:raise ValueError('工具包导入后内容已变化，拒绝激活；请重新导入正式包')
            compatible=installed_compatibility(p['path'])
            if compatible['status']=='incompatible':raise ValueError(compatible['message'])
        old=self.package()
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');c.execute('UPDATE kv SET value=? WHERE key="active_package"',(json.dumps(pid),))
            c.execute('INSERT INTO activations(old_id,new_id,time) VALUES(?,?,?)',(old['id'],pid,stamp()))
        self.store.event('version.activated','切换受管版本 '+old['version']+' → '+p['version'],details={'old':old['id'],'new':pid})
        return {'active':p,'note':'原数据与指令历史保留。用户覆盖按版本隔离，需要人工合并；宿主中已加载上下文需要刷新。'}
    def versions(self):
        from .releases import history
        with self.store.db() as c:rows=c.execute('SELECT * FROM activations ORDER BY id DESC LIMIT 50').fetchall()
        return {'packages':self.packages(),'history':[dict(r) for r in rows],
                'software_history':history(self.store),'product_version':VERSION,
                'channel':'stable','manager_version':VERSION,'api_version':API_VERSION,
                'distribution':self.distribution(),
                'note':'软件与内置制作工具由安装包统一更新。扩展工具包单独导入和切换。'}
    def register_export(self,path):
        path=Path(path).resolve()
        if not path.is_relative_to(self.data/'exports') or not path.is_file():raise ValueError('导出文件不在允许范围')
        eid=secrets.token_hex(12)
        with self.store.db() as c:c.execute('INSERT INTO exports VALUES(?,?,?,?)',(eid,str(path),path.name,stamp()))
        return {'file_id':eid,'name':path.name,'size':path.stat().st_size}
    def export_file(self,eid):
        with self.store.db() as c:r=c.execute('SELECT path FROM exports WHERE id=?',(eid,)).fetchone()
        if not r:raise ValueError('导出文件不存在')
        p=Path(r[0]).resolve()
        if not p.is_relative_to(self.data/'exports') or not p.is_file():raise ValueError('导出路径无效')
        return p
    def export_data(self):
        dest=self.data/'exports'/('manager-config-'+secrets.token_hex(4)+'.json');dest.parent.mkdir(exist_ok=True)
        with self.store.db() as c:
            docs=[dict(x) for x in c.execute('SELECT * FROM docs').fetchall()];overrides=[dict(x) for x in c.execute('SELECT * FROM overrides').fetchall()]
        data={'format':API_VERSION,'created':stamp(),'settings':self.settings(),'packages':self.packages(),'instructions':docs,'tool_overrides':overrides,'commands':self.commands(),'logs':self.store.logs(limit=1000),'scope':'管理配置快照；不包含 PPT 项目、密钥、软件包代码。'}
        dest.write_text(json.dumps(redact(data),ensure_ascii=False,indent=2),encoding='utf-8');self.store.event('config.exported','已导出管理配置与最近最多1000条日志')
        return self.register_export(dest)
    def integration(self):
        from .integrations import config_for
        return config_for(self)
    def export_integration(self):
        from .integrations import export_bundle
        return export_bundle(self)
    def register_plan(self):
        from .integrations import plan
        return plan(self)
    def register_apply(self,confirm_id):
        from .integrations import apply
        return apply(self,confirm_id)
    def context(self,project=None):
        p=self.package()
        if not p['enabled']:raise ValueError('当前工具包已在管理器中停用')
        from .production_storage import locations, startup_prompt
        from .project_context import ProjectContext
        from .policy import authorize
        from .learning import preferences as learning_preferences
        current=None
        if project is not None:
            root,_=authorize(self,project)
            current=ProjectContext(self,root).snapshot()
        from .material_policy import effective
        return {'material_policy':effective(self,project),'active':p,'settings':self.settings(),'distribution':self.distribution(),'instance':self.instance(),'skill':self.document('SKILL.md')['content'] if (Path(p['path'])/'SKILL.md').is_file() else '',
            'storage':locations(self),'project_context':current,'startup_prompt':startup_prompt(self)['text'],
            'learning':{'entry':'toolbox_learning','preferences':learning_preferences(self),
                        'task_experience_entry':'toolbox_retrospective',
                        'sequence':['send_final_ppt','user_acceptance','artwork_choice','learning_consent','archive'],
                        'library_directory':str(self.data/'learning'),
                        'source_policy':'Delivered sources are intake candidates, not verified skills. Use current governed capture/apply/validate/activate and current visual evidence.'},
            'instructions':[{k:v for k,v in x.items()} for x in self.commands() if x['enabled']],
            'tool_policy':{'disabled':[x['id'] for x in self.catalog() if not x['enabled']]},
            'runtime_instructions':'本管理配置优先将根工具箱 start/next/submit 等调用映射到 workflow.* 注册项，经 manager execute 执行；其他 ops/bench 使用对应工具 ID。原始 Skill 中直接 toolbox.py 的示例为核心用法，不代表已进入受管日志或受管开关。',
            'entry_argv':[sys.executable,str(self.root/'manager.py'),'--data-dir',str(self.data),'execute','--tool'],
            'scope':'用户覆盖通过 context/manual 生效；工具启停仅通过 execute 生效。直接运行旧脚本不会受此管理器约束。'}
    def icons(self,op,args=None,source='mcp',project_scope=None):
        from .project_activity import observe_call
        return observe_call(self,'icons.'+op,args,source,lambda:self._icons(op,args,source),project_scope)
    def _icons(self,op,args=None,source='mcp'):
        import time
        with self.lock:
            self.icon_activity={'call_id':secrets.token_hex(16),'phase':'loading_icon_modules',
                                'tool':'icons_'+op,'started':time.monotonic(),'dispatched':False}
            try:
                from .icons.service import IconService
                if not self.package()['enabled']:raise ValueError('当前工具包已停用')
                if not hasattr(self,'_icon_service'):
                    self._icon_service=IconService(self)
                return self._icon_service.call(op,args,source)
            finally:
                self.icon_activity=None
    def execute(self,tid,args):
        if tid.startswith('graphics.'):
            if args==['--help']:return {'usage':'--json <request.json>; see references/graphics-construction.md'}
            if len(args)!=2 or args[0]!='--json':raise ValueError('Use --json <request.json>')
            return self.graphics(tid.split('.',1)[1],json.loads(Path(args[1]).read_text(encoding='utf-8-sig')),source='cli')
        if tid.startswith('icons.'):
            if args==['--help']:return {'usage':'--json <request.json>; see references/icon-library.md'}
            if len(args)!=2 or args[0]!='--json':raise ValueError('Use --json <request.json>')
            body=json.loads(Path(args[1]).read_text(encoding='utf-8-sig'))
            return self.icons(tid.split('.',1)[1],body,source='cli')
        from .contracts import COMMANDS
        if tid in {'workflow.'+c for c in {*WORKFLOWS, *COMMANDS}} and '--help' not in args:
            from .execution import execute
            return execute(self,tid.split('.',1)[1],args,source='cli')
        project=None
        if args[:1]==['--project']:
            if len(args)<2:raise ValueError('Missing --project path')
            project=args[1];args=args[2:]
            if args[:1]==['--']:args=args[1:]
        try:return self._execute(tid,args,project)
        except Exception as exc:
            self.store.event('tool.rejected','受管调用未完成 '+str(tid),status='error',source='cli',details={'error_type':type(exc).__name__})
            raise
    def execute_workflow(self,command,arguments,source='mcp',rpc_id=None):
        from .execution import execute
        return execute(self,command,arguments,source=source,rpc_id=rpc_id)
    def authorize_project(self,project,input_roots,connection=None,*,approval_mode='owner',settings_revision=None):
        """Persist an owner decision or the owner's saved automatic-approval policy."""
        if approval_mode not in {'owner','automatic'}:raise ValueError('Unknown approval mode')
        from .policy import plain_path, PolicyDenied
        from .project_context import ProjectContext
        path=ProjectContext(self,project).root;roots=[plain_path(p) for p in input_roots]
        package=plain_path(self.package()['path'])
        if (path.is_relative_to(package) or package.is_relative_to(path)
                or path.is_relative_to(self.data) or self.data.is_relative_to(path)):
            raise PolicyDenied('Project must be separate from package and management data')
        if any(not r.is_dir() for r in roots):raise ValueError('Input roots must be existing directories')
        def save(c):
            record=c.execute("SELECT value FROM kv WHERE key='project_authorizations'").fetchone()
            rows=json.loads(record[0]) if record else {}
            rows[str(path)]={'write':True,'input_roots':[str(r) for r in roots],'authorized_at':stamp()}
            if approval_mode=='automatic':
                rows[str(path)].update(approval_mode=approval_mode,settings_revision=settings_revision)
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      ('project_authorizations',json.dumps(rows,ensure_ascii=False)))
            from .storage import redact
            details=redact({'project':str(path),'input_roots':[str(r) for r in roots]})
            automatic=approval_mode=='automatic'
            if automatic:details.update(approval_mode=approval_mode,settings_revision=settings_revision)
            c.execute('INSERT INTO events(time,source,action,status,message,details) VALUES(?,?,?,?,?,?)',
                      (stamp(),'policy' if automatic else 'owner','project.auto_authorized' if automatic else 'project.authorized','ok',
                       'Project paths approved by saved automatic-approval setting' if automatic else 'Owner configured project paths',json.dumps(details,ensure_ascii=False)))
            return rows[str(path)]
        if connection is not None:
            return save(connection)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return save(c)
    def _execute(self,tid,args,project_context=None):
        from .execution import registered_context, snapshot, code_version
        p=self.package();s=self.settings();r=self.tool(tid)
        if not s['agent_execution_enabled']:raise ValueError('受管执行尚未启用，请在设置中由用户开启')
        if not p['trusted'] or not p['enabled'] or not r['enabled']:raise ValueError('当前包或工具未启用 / 未信任')
        if tid=='bench.run' and not s['network_benchmarks_enabled']:raise ValueError('联网评测在管理器中被禁用')
        if r['kind'] not in {'python','powershell'}:raise ValueError('该条目为手册、模块或宿主能力，请按说明调用')
        if not isinstance(args,list) or any(not isinstance(a,str) or '\x00' in a or len(a)>8000 for a in args) or len(args)>200:raise ValueError('argv 参数不合法')
        project=registered_context(self,tid,args,project_context)
        # Explicit local CLI invocation; not a sandbox. No shell expansion. Existing tool keeps its own permission checks.
        entry=(Path(p['path'])/r['entry']).resolve()
        if not entry.is_relative_to(Path(p['path']).resolve()) or not entry.is_file():raise ValueError('工具路径非法')
        if r['kind']=='python':argv=python_tool_argv(s['python_path'] or sys.executable,p['path'],r['entry'],[*r.get('prefix',[]),*args])
        else:
            shell=powershell_path(s['powershell_path'])
            if os.name!='nt' or not shell:raise ValueError('需要 Windows 和 PowerShell')
            argv=[shell,'-NoProfile','-File',str(entry),*r.get('prefix',[]),*args]
        from .project_context import ProjectContext
        call_id=secrets.token_hex(16)
        outdir=ProjectContext(self,project).path('logs/tool-calls/'+call_id) if project else self.data/'runs'/call_id
        outdir.mkdir(parents=True,exist_ok=False)
        before=snapshot(project) if project else {}
        version=code_version(Path(p['path']))
        (outdir/'code-version.json').write_text(json.dumps(version,indent=2),encoding='utf-8')
        details={'call_id':call_id,'tool_id':tid,'source':'cli','arg_count':len(args),
                 'project':str(project) if project else None,'project_id':before.get('project_id'),
                 'task_id':before.get('task_id'),'revision_before':before.get('revision'),
                 'revision_after':None,'started_at':stamp(),'ended_at':None,
                 'command_status':'started','workflow_status':before.get('workflow_status'),
                 'parameters':{'arg_count':len(args)},'usage_maintenance':args==['--help'],'output_directory':str(outdir),
                 'code':{k:v for k,v in version.items() if k!='file_hashes'},
                 'null_note':'Non-project CLI help/diagnostics have no workflow identity'}
        self.store.event('tool.started','受管调用 '+tid,source='cli',details=details)
        try:
            from contextlib import nullcontext
            from scripts.runtime_env import office_guard
            if project and (project/'calibrations').is_dir() and tid.startswith('office.'):
                sys.path.insert(0,str(Path(p['path'])/'scripts'))
                from calibration_exports import cli_export, track
                from workflow_store import locked
                export=cli_export(tid,args)
                with locked(project), office_guard(self.data/'office-writer.lock'):
                    with track(project,*export) if export else nullcontext():
                        run=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=min(r.get('timeout_seconds',240),10 if args==['--help'] else 900),shell=False,env={**child_environment(s['powershell_path']), 'PPT_EXPERIENCE_ROOT': str(self.data/'experience-library'), 'PPT_USAGE_ROOT':str(self.data/'usage'), 'PPT_MANAGED_CALL_ID':call_id, 'PPT_USAGE_PROJECT':str(project or ''), 'PPT_USAGE_TASK':str(before.get('task_id') or '')},cwd=project or self.root)
            else:
                with office_guard(self.data/'office-writer.lock') if tid.startswith('office.') else nullcontext():
                    run=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=min(r.get('timeout_seconds',240),10 if args==['--help'] else 900),shell=False,env={**child_environment(s['powershell_path']), 'PPT_EXPERIENCE_ROOT': str(self.data/'experience-library'), 'PPT_USAGE_ROOT':str(self.data/'usage'), 'PPT_MANAGED_CALL_ID':call_id, 'PPT_USAGE_PROJECT':str(project or ''), 'PPT_USAGE_TASK':str(before.get('task_id') or '')},cwd=project or self.root)
            status='completed' if run.returncode==0 else 'action_required' if run.returncode in r.get('waiting_exit_codes',[]) else 'tool_failed'
            (outdir/'stdout.json').write_text(run.stdout,encoding='utf-8');(outdir/'stderr.log').write_text(run.stderr,encoding='utf-8')
            after=snapshot(project) if project else {}
            result={'call_id':call_id,'tool_id':tid,'command_status':status,'workflow_status':after.get('workflow_status'),'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'output_directory':str(outdir)}
            if project:result['project_context']=ProjectContext(self,project).snapshot()
            (outdir/'call.json').write_text(json.dumps({**details,'ended_at':stamp(),'command_status':status},ensure_ascii=False,indent=2),encoding='utf-8')
            self.store.event('tool.finished','调用结束 '+tid,status='error' if status=='tool_failed' else 'waiting' if status=='action_required' else 'ok',source='cli',details={**details,'ended_at':stamp(),'revision_after':after.get('revision'),'returncode':run.returncode,'command_status':status})
            return result
        except Exception as e:
            self.store.event('tool.finished','调用失败 '+tid,status='error',source='cli',details={**details,'ended_at':stamp(),'command_status':'outcome_unknown' if isinstance(e,subprocess.TimeoutExpired) else 'failed','error_type':type(e).__name__});raise
    def graphics(self,op,args=None,source='mcp',project_scope=None):
        from .graphics import call
        from .project_activity import observe_call
        return observe_call(self,'graphics.'+op,args,source,lambda:call(self,op,args,source),project_scope)

    def call(self,op,args=None):
        a=args or {}
        if not isinstance(a,dict):raise ValueError('请求需要对象')
        if op=='project.inspect':
            from .project_inspection import inspect
            return inspect(self,a)
        if op.startswith('usage.'):
            from .usage import call
            return call(self,op[6:],a)
        if op.startswith('experience.'):
            from .source_experience import call
            return call(self,op[11:],a)
        if op == 'retrospective':
            from .retrospective import call
            return call(self,a)
        if op.startswith('learning.'):
            from .learning import call
            return call(self,op[9:],a)
        if op.startswith('agent.'):
            from .agent_setup import call
            return call(self,op[6:],a)
        if op.startswith('prompt.'):
            from .prompt_editor import call
            return call(self,op[7:],a)
        from .production_storage import startup_prompt
        from .folder_picker import pick_directory
        routes={
          'startup-prompt':lambda:startup_prompt(self,a),
          'storage.pick-directory':lambda:pick_directory(self,a),
          'storage.setup':lambda:self.open_setup(),
          'source':lambda:self.source(a['id']),
          'boot':lambda:self.boot(),'tools':lambda:self.catalog(a.get('package_id')),'tool':lambda:self.tool(a['id']),
          'packages':lambda:self.packages(),'versions':lambda:self.versions(),'settings':lambda:self.settings(),'settings.save':lambda:self.save_settings(a),
          'toggle':lambda:self.toggle(a['kind'],a.get('target',''),a['enabled'],a.get('package_id')),
          'docs':lambda:self.docs(a.get('package_id')),'doc':lambda:self.document(a['path'],a.get('package_id')),
          'doc.save':lambda:self.save_document(a['path'],a.get('content',''),a['revision'],a.get('package_id'),a.get('restore_revision')),
          'commands':lambda:self.commands(),'command.save':lambda:self.save_command(a),
          'doctor':lambda:self.doctor(),'diagnostic':lambda:self.diagnostic(a['kind']),
          'package.commit':lambda:self.commit_import(a['confirm_id']),'package.trust':lambda:self.trust(a['id'],a.get('acknowledge')),
          'package.activate':lambda:self.activate(a['id']),
          'logs':lambda:self.store.logs(a.get('query',''),a.get('status',''),a.get('limit',self.settings()['log_page_size'])),
          'integration':lambda:self.integration(),'integration.export':lambda:self.export_integration(),
          'integration.plan':lambda:self.register_plan(),'integration.apply':lambda:self.register_apply(a['confirm_id']),
          'config.export':lambda:self.export_data(),'context':lambda:self.context()}
        if op not in routes:raise ValueError('操作不存在')
        try:return routes[op]()
        except Exception as exc:
            self.store.event(op,'操作未完成 '+op,status='error',details={'error':str(exc)})
            raise
