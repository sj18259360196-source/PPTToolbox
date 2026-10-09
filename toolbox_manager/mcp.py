"""JSON-RPC stdio discovery plus governed workflow and local adapters."""
from __future__ import annotations
import contextlib,copy,json,sys,os
from .service import Manager
from . import VERSION
from scripts.project_flow import PATCH_SCHEMA as FLOW_SCHEMA

def schema(p=None,required=()):return {'type':'object','properties':p or {},'required':list(required),'additionalProperties':False}
S={'type':'string'}
TOOLS=[
 ('toolbox_project_activity','Read registered project work chain, current stage revision, observed calls and stage recommendations. Read before a checkpoint retry after a version conflict.',schema({'project':S},['project'])),
 ('toolbox_checkpoint','Register an explicit major-stage declaration. Begin intake, transition through plan/production/revision/delivery, then finish with delivery files. Ordinary tool calls need no progress report. Reuse checkpoint_id for retries. used_experiences records actual adoption only. Optional flow contains node patches (id, title for new nodes, after predecessor IDs, status); software lays out the graph. No per-tool reporting.',
  schema({'project':S,'checkpoint_id':S,'run_id':S,'expected_revision':{'type':'integer','minimum':0},
    'event':{'enum':['begin','transition','finish','replan','blocked','pause','resume']},
    'stage':{'enum':['intake','plan','production','revision','delivery']},'result_summary':S,'next_action':S,
    'artifact_refs':{'type':'array','items':S,'maxItems':30},'blocker':{'type':['string','null']},
    'used_experiences':{'type':'array','items':S,'maxItems':20},'declared_at':S,'flow':FLOW_SCHEMA},
    ['project','checkpoint_id','run_id','expected_revision','event','result_summary'])),
 ('toolbox_project_inspect','Read project identity, paginate current required views, or preflight a scene and explicit full-ID edits. Returns bounded crop/occlusion warnings; never modifies files or approves viewing.',schema({'project':S,'action':{'enum':['identity','views','scene']},'scene':S,'scan_crops':{'type':'boolean'},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':20},'changes':{'type':'array','maxItems':100,'items':schema({'object_id':S,'set':{'type':'object'}},['object_id','set'])}},['project'])),
 ('toolbox_material_policy','读取全局或当前项目的素材持久授权。允许范围内无需重复询问；宿主能力和当前用户限制仍适用。',schema({'project':S})),
 ('toolbox_call_status','读取当前 MCP 连接正在处理的调用和耗时；不重试、不终止写入。',schema()),
 ('toolbox_runtime_check','检查指定 Python 工具的正式受管启动入口，只执行 --help，保留调用日志，不制作 PPT。',
  schema({'ids':{'type':'array','items':{'type':'string','minLength':1},'minItems':1,'maxItems':8}},['ids'])),
 ('toolbox_usage','Read usage counts with action summary/detail, or record an experience citation with action cite. cite requires an authorized project, existing task_id, experience id, concrete reason and optional object_ids. A citation is Agent-reported use, never verification or acceptance.',
  {'type':'object','oneOf':[schema({'action':{'enum':['summary','detail']},'kind':{'enum':['experience','tool','icon','skill']},'id':S,'days':{'enum':['7','30','all']},'include_tests':{'type':'boolean'},'offset':{'type':'integer','minimum':0}},['action']),
             schema({'action':{'const':'cite'},'id':S,'project':S,'task_id':S,'reason':S,'object_ids':{'type':'array','items':S}},['action','id','project','task_id','reason'])]}),
 ('toolbox_learning','Read the current installed learning library or a delivered source. Never enables a skill or approves evidence.',
  schema({'id':S})),
 ('toolbox_verify_connection','验证设置页的一次性连接口令，不授予项目执行权限。',schema({'challenge':S},['challenge'])),
 ('toolbox_status','读取管理器和当前启用版本；不要把注册来源当作宿主已安装。',schema()),
 ('toolbox_search','检索当前包中已启用工具，返回实际入口及条件。',schema({'query':S})),
 ('toolbox_describe','读取一个已启用工具的参数、手册和受管调用 argv。',schema({'id':S},['id'])),
 ('toolbox_context','读取当前 Skill 用户覆盖、自定义指令、执行开关和禁用工具；按需加载。',schema()),
 ('toolbox_project_bind','为本 Agent 会话绑定项目。project 使用用户明确指定的目录；name 在默认根目录下新建任务。返回 context_id，不创建文件或授予权限。',
  {**schema({'project':S,'name':S}),'oneOf':[{'required':['project'],'not':{'required':['name']}},{'required':['name'],'not':{'required':['project']}}]}),
 ('toolbox_manual','读取当前版本的指定手册及用户覆盖；不提供path则列出手册。',schema({'path':S})),
 ('toolbox_logs','读取管理器与受管入口的最近日志，不包含 Codex 全部历史。',schema({'query':S})),
]
DESCRIPTIONS={
 'route_check':'Check attributed current-region requirements and persist a bounded route; no Office or task consumption.',
 'route_report':'Read regional routes and recheck actual use outcomes without Office or workflow changes.',
 'skill_capture':'Capture an attributed native fragment as a candidate declarative recipe.',
 'skill_search':'Search enabled local recipes or read a version contract without Office execution.',
 'skill_apply':'Compile a scoped recipe through the existing governed probe workflow.',
 'skill_validate':'Derive scoped validation from actual applied-task delivery evidence.',
 'skill_activate':'Enable or disable an evidence-validated version in the current local library.',
 'calibrate_plan':'冻结有界校准参数、参考区域、评分规则和累计预算，不启动Office。',
 'calibrate_step':'程序自动选择下一组参数，经受管Office执行有限试验，不自动采用。',
 'calibrate_report':'只读取已有校准记录与候选证据，不渲染或推进。',
 'probe':'基于当前region任务生成独立可编辑样件，不消耗token或改变主revision。',
 'patch':'按已有区域授权对指定基准PPTX定点修改新副本，保存重开并同步scene。',
 'compare':'生成参考对照及范围外结构/像素回归；不自动审批视觉。',
 'adopt':'核对试制与对照身份后成对采用，清除旧任务与验收，不等于交付。',
 'start':'从已授权参考图或既有 scene 建立新项目，不覆盖已有项目。',
 'next':'推进已就绪的构建/导出步骤并返回当前任务，有写入及 Office 副作用。',
 'submit':'提交实际完成的 result，核对任务身份、revision 和哈希。复杂路径优先把 result 单独保存为项目内 UTF-8 JSON，用 result_file 与 result_sha256 替代 result，避免 1 MiB MCP 上限。文件上限 16 MiB。设置 return_next=true 接续任务；accepted_task 表明已提交，不得重放。',
 'validate_response':'预检当前任务响应，返回字段错误，不消费任务、不写工作流状态、不启动 Office。大结果用 result_file 与 result_sha256 替代 result，文件只含 result 对象。调用审计仍保留。',
 'revision_candidate':'从当前交付版创建局部修订候选，保留旧交付并清空新候选的验收记录。',
 'status':'读取当前任务与工作流，不修复中断或自动重试。',
 'revise':'按明确 slide/region 和 reason 返修，保留历史证据。',
 'finish':'重核交付门禁；可推进内部步骤，仅在门禁通过后写入交付。',
}
class MCP:
    def __init__(self,data_dir,**kw):self.manager=Manager(data_dir,**kw);self.ready=False;self.current_project=None;self.client_info={};self.activity=None;self.active_call=None
    def specs(self):
        from .retrospective import SPEC
        from .contracts import schemas
        contracts=copy.deepcopy(schemas(self.manager.root))
        for value in contracts.values():
            value['properties']['context_id']={'type':'string','minLength':1}
            value['required']=[k for k in value['required'] if k!='project']
            value['anyOf']=[{'required':['project']},{'required':['context_id']}]
        from .icons.contracts import SPECS
        from .graphics import SPECS as GRAPHICS
        return TOOLS+[("toolbox_retrospective","After sending the final PPT, record explicit user acceptance, then artwork retention choice, then learning consent. Never invent user replies. Archive observable process and decision summaries, not private reasoning. list retrieves task-scoped experience; improvements remain proposals.",SPEC)]+[("graphics_"+op,d,copy.deepcopy(s)) for op,(d,s) in GRAPHICS.items()]+[("icons_"+op,d,s) for op,(d,s) in SPECS.items()]+[
            ('rebuild_'+cmd,DESCRIPTIONS[cmd],s)
            for cmd,s in contracts.items()
        ]
    def call(self,name,args,rpc_id=None):
        m=self.manager
        if name=='toolbox_checkpoint':
            from .project_hub import checkpoint
            return checkpoint(m,args)
        if name=='toolbox_project_activity':
            from .project_hub import snapshot
            return snapshot(m,args['project'])
        if name=='toolbox_call_status':
            import time
            from .recovery import connection_diagnostics
            active=self.active_call
            if active and active.get('tool')=='toolbox_call_status':active=None
            return {'status':'running' if active else 'idle',
                    'tool':active['tool'] if active else None,
                    'elapsed_seconds':round(time.monotonic()-active['started'],1) if active else 0,
                    'execution_phase':getattr(m,'icon_activity',None),
                    'next_action':'Wait or inspect managed logs; do not replay writes' if active else 'Ready',
                    'diagnostics':connection_diagnostics(m,self.current_project,initialized=self.ready,
                                                        client=self.client_info,active_call=active)}
        if name=='toolbox_project_inspect':
            from .project_inspection import inspect
            return inspect(m,args)
        if name=='toolbox_runtime_check':
            from .runtime_check import check
            return check(m,args['ids'])
        if name=='toolbox_usage':
            from .usage import call
            return call(m,args['action'],{k:v for k,v in args.items() if k!='action'})
        if name=='toolbox_retrospective':
            from .retrospective import call
            return call(m,args,source='mcp')
        if name=='toolbox_learning':
            return m.call('learning.source',args) if args.get('id') else m.call('learning.status')
        if name.startswith("graphics_"):return m.graphics(name[9:],args,source="mcp",project_scope=(self.current_project or {}).get('project_root'))
        if name.startswith("icons_"):return m.icons(name[6:],args,source="mcp",project_scope=(self.current_project or {}).get('project_root'))
        if name.startswith('rebuild_'):
            from .project_context import resolve_call,refresh
            if self.current_project is not None or 'context_id' in args:
                args,self.current_project=resolve_call(m,self.current_project,args)
                if name=='rebuild_start' and not self.current_project['initialized']:
                    from pathlib import Path
                    args={**args,'in_place':Path(args['project']).is_dir()}
            result=m.execute_workflow(name[len('rebuild_'):],args,source='mcp',rpc_id=rpc_id)
            if self.current_project is not None:
                self.current_project=refresh(m,self.current_project)
                result['project_context']=self.current_project
            return result
        if name=='toolbox_status':return m.boot()
        if name=='toolbox_logs':return m.store.logs(args.get('query',''),limit=100)
        p=m.package()
        if not p['enabled']:raise ValueError('当前工具包已在管理器中停用')
        if name=='toolbox_search':
            return m.search(args.get('query',''))
        if name=='toolbox_verify_connection':
            from .agent_setup import verify_connection
            return verify_connection(m,args['challenge'],self.client_info,os.environ.get('PPT_TOOLBOX_CONNECTION_PROBE')=='1')
        if name=='toolbox_material_policy':
            from .material_policy import effective
            return effective(m,args.get('project') or (self.current_project or {}).get('project_root'))
        if name=='toolbox_project_bind':
            from .project_context import bind
            self.current_project=bind(m,**args)
            return self.current_project
        if name=='toolbox_context':
            from .project_context import refresh
            if self.current_project is not None:self.current_project=refresh(m,self.current_project)
            from .material_policy import effective
            from .recovery import connection_diagnostics
            from .project_hub import stage_context
            phase = stage_context(m,self.current_project['project_root']) if self.current_project else None
            return {**m.context(),'project_context':self.current_project,
                    'stage_context':phase,
                    'connection_diagnostics':connection_diagnostics(m,self.current_project,initialized=self.ready,
                        client=self.client_info,active_call=self.active_call),
                    'material_policy':effective(m,(self.current_project or {}).get('project_root'))}
        if name=='toolbox_describe':
            r=m.tool(args['id'])
            if not r['enabled'] and not args['id'].startswith('native.'):raise ValueError('此工具已停用')
            return r
        if name=='toolbox_manual':
            path = args.get('path', '')
            if path.startswith('native/'):
                return m.native_card(path[len('native/'):])
            return m.document(path) if path else m.docs()
        raise ValueError('Unknown tool')
    def handle(self,req):
        monitor=self.activity
        calling=self.ready and req.get('method')=='tools/call' and req.get('id') is not None
        if monitor and calling:monitor.begin((req.get('params') or {}).get('name','未知工具'))
        try:
            result=self._handle(req)
            if monitor and req.get('method')=='initialize' and result and 'result' in result:monitor.connect(self.client_info)
            if monitor and calling:
                error=''
                outcome=None
                if result and 'error' in result:error=result['error'].get('message','调用失败')
                elif result and result.get('result',{}).get('isError'):
                    error=' '.join(v.get('text','') for v in result['result'].get('content',[])) or '工具调用失败'
                if result:
                    structured=result.get('result',{}).get('structuredContent',{})
                    outcome=structured.get('recovery') if isinstance(structured,dict) else None
                monitor.finish(error,outcome)
            return result
        except Exception as exc:
            if monitor and calling:monitor.finish(str(exc))
            raise
    def _handle(self,req):
        rid=req.get('id');method=req.get('method')
        def ok(r):return {'jsonrpc':'2.0','id':rid,'result':r}
        def err(code,msg):return {'jsonrpc':'2.0','id':rid,'error':{'code':code,'message':msg}}
        if req.get('jsonrpc')!='2.0':return err(-32600,'JSON-RPC 2.0 required')
        if method=='initialize':
            requested=req.get('params',{}).get('protocolVersion');self.ready=True
            self.client_info=req.get('params',{}).get('clientInfo',{})
            return ok({'protocolVersion':requested if requested in {'2025-03-26','2025-06-18','2025-11-25'} else '2025-11-25',
                'capabilities':{'tools':{'listChanged':True}},'serverInfo':{'name':'ppt-toolbox-manager','version':VERSION},
                'instructions':'Read toolbox_material_policy or context.material_policy for saved material consent. Within allowed scope do not ask again; current user restrictions and host controls still apply. Use toolbox_context and rebuild_* tools for authorized workflow execution and local probe/patch/compare/adopt. All share the managed CLI service. next, probe, patch and compare can build or render. Owner enables execution and chooses manual or automatic project approval in settings. When auto_approve_project_requests is enabled, rebuild_start applies that saved policy and continues in the same call. Rejected projects remain denied. Other tools remain on the managed CLI. Never bypass disabled capabilities or fabricate visual reviews.'})
        if rid is None:return None
        if not self.ready:return err(-32002,'Initialize first')
        if method=='ping':return ok({})
        if method=='tools/list':return ok({'tools':[{'name':n,'description':d,'inputSchema':s,'annotations':{'readOnlyHint':n not in {'toolbox_checkpoint','toolbox_verify_connection','toolbox_retrospective','toolbox_usage'} and (not n.startswith(('rebuild_','icons_','graphics_')) or n in {'icons_search','icons_inspect','icons_stats','icons_providers','icons_fragment','icons_trace_fragment','graphics_inspect','graphics_validate','graphics_preview','graphics_fit_gradient','graphics_analyze','graphics_material_recipe','graphics_audit_sources'}) or n in {'rebuild_status','rebuild_validate_response','rebuild_calibrate_report','rebuild_route_report'},'destructiveHint':n in {'rebuild_submit','rebuild_revise','rebuild_adopt'},'openWorldHint':False}} for n,d,s in self.specs()]})
        if method=='tools/call':
            try:
                params=req.get('params',{});name=params['name'];args=params.get('arguments',{})
                spec=next((s for n,d,s in TOOLS if n==name),None)
                if spec is None:spec=next((s for n,d,s in self.specs() if n==name),None)
                if spec is None:return err(-32602,'Unknown tool')
                # Workflow validation is inside the shared service so invalid
                # calls get the same audit lifecycle and status as CLI calls.
                if not name.startswith('rebuild_'):
                    from jsonschema import Draft202012Validator
                    if not Draft202012Validator(spec).is_valid(args):
                        def invalid(): raise ValueError('Invalid tool arguments')
                        if name.startswith(('icons_','graphics_')):
                            from .project_activity import observe_call
                            observe_call(self.manager,name.replace('_','.',1),args,'mcp',invalid,(self.current_project or {}).get('project_root'))
                        invalid()
                with contextlib.redirect_stdout(sys.stderr):r=self.call(name,args,rpc_id=rid)
                if not name.startswith(('rebuild_','icons_','graphics_')) and name!='toolbox_retrospective':self.manager.store.event('mcp.read',name,source='mcp',details={'target_id':args.get('id')})
                if isinstance(r,dict):r={k:v for k,v in r.items() if k not in {'stdout','stderr'}}
                response={'content':[{'type':'text','text':json.dumps(r,ensure_ascii=False,allow_nan=False)}]}
                if isinstance(r,dict):
                    response['structuredContent']=r
                    response['isError']=(r.get('command_status') in {'failed','tool_failed','invalid_arguments','permission_denied','outcome_unknown'}
                                         or (r.get('recovery') or {}).get('outcome')=='accepted_next_failed')
                return ok(response)
            except Exception as e:return ok({'isError':True,'content':[{'type':'text','text':str(e)}]})
        return err(-32601,'Method not found')

def run(data_dir):
    if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8',errors='strict')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='strict')
    m=MCP(data_dir)
    from .agent_presence import Session
    m.activity=Session(m.manager.data)
    from .desktop import launch_for_agent
    if os.environ.get("PPT_TOOLBOX_CONNECTION_PROBE")!="1":launch_for_agent(m.manager)
    import threading,queue,time
    from collections import deque
    from .update_signal import requested,idle
    incoming=queue.Queue();completed=queue.Queue();waiting=deque();active=None;closing=False
    protocol_output=sys.stdout
    def emit(value):
        protocol_output.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');protocol_output.flush()
    def handle(req):
        try:completed.put(m.handle(req))
        except Exception:completed.put({'jsonrpc':'2.0','id':req.get('id'),'error':{'code':-32603,'message':'Request failed; inspect logs'}})
    def read():
        try:
            for line in sys.stdin:incoming.put(line)
        finally:incoming.put(None)
    threading.Thread(target=read,daemon=True).start()
    try:
        while True:
            if active is not None:
                try:
                    result=completed.get_nowait();active.join();active=None;m.active_call=None
                    if result is not None:emit(result)
                except queue.Empty:pass
            if active is None and waiting:
                req=waiting.popleft()
                m.active_call={'tool':req.get('params',{}).get('name'),'started':time.monotonic()}
                active=threading.Thread(target=handle,args=(req,),daemon=True);active.start()
            if closing and active is None:break
            if active is None and requested(m.manager.data) and idle(m.manager.data):break
            try:line=incoming.get(timeout=.3)
            except queue.Empty:continue
            if line is None:
                closing=True
                continue
            try:
                from .payload_transport import oversized_rpc
                rejected = oversized_rpc(line)
                if rejected is not None:
                    try:
                        m.manager.store.event('mcp.rejected', 'MCP payload too large; not dispatched',
                            source='mcp', status='error', details=rejected['error']['data'])
                    except Exception:
                        pass  # Audit failure must not turn a known rejection into a parse error.
                    # Attribute the rejected attempt without invoking the requested tool.
                    try:
                        from .payload_transport import WORKER_BYTES, PayloadTooLarge
                        if rejected['error']['data']['request_bytes'] <= WORKER_BYTES:
                            rejected_req = json.loads(line)
                            params = rejected_req.get('params', {})
                            from .project_activity import observe_call
                            def reject_payload():
                                raise PayloadTooLarge('MCP 请求超过 1 MiB，尚未执行。' +
                                    ('请将 result 保存为项目内 JSON，通过 result_file 和 result_sha256 提交。'
                                     if params.get('name') in {'rebuild_submit', 'rebuild_validate_response'} else
                                     '请核对当前工具支持的文件输入或受管 CLI 文件入口，勿重发同一超限请求。'))
                            observe_call(m.manager, str(params.get('name', 'mcp')).replace('rebuild_', 'workflow.', 1),
                                params.get('arguments', {}), 'mcp', reject_payload,
                                (m.current_project or {}).get('project_root'))
                    except Exception:
                        pass  # The correlated transport rejection must always reach the host.
                    emit(rejected)
                    continue
                req=json.loads(line)
                if not isinstance(req,dict):raise ValueError('Request must be object')
                if active is not None and req.get('method')=='tools/call':
                    if req.get('params',{}).get('name')=='toolbox_call_status':
                        value=m.call('toolbox_call_status',{})
                        value['queued_calls']=len(waiting)
                        r={'jsonrpc':'2.0','id':req.get('id'),'result':{'content':[{'type':'text','text':json.dumps(value)}],'structuredContent':value}}
                    elif len(waiting)>=16:
                        r={'jsonrpc':'2.0','id':req.get('id'),'error':{'code':-32001,
                            'message':'MCP request queue is full; call toolbox_call_status. This request was not dispatched.'}}
                    else:waiting.append(req);r=None
                elif req.get('method')=='tools/call':
                    m.active_call={'tool':req.get('params',{}).get('name'),'started':time.monotonic()}
                    active=threading.Thread(target=handle,args=(req,),daemon=True);active.start();r=None
                else:r=m.handle(req)
            except Exception:r={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
            if r is not None:emit(r)
    finally:m.activity.close()
