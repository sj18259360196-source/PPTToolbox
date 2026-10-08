import {api,copy} from './api.js';
import {showAgentLive} from './agent-live.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function promptMarkup(text,paths){
 const values=[...new Set(Object.values(paths).filter(Boolean))].sort((a,b)=>b.length-a.length);
 let rest=String(text),html='';
 while(rest){
  let index=-1,path='';
  for(const value of values){const at=rest.indexOf(value);if(at>=0&&(index<0||at<index)){index=at;path=value;}}
  if(index<0){html+=esc(rest);break;}
  html+=esc(rest.slice(0,index))+`<strong class="prompt-path-highlight">${esc(path)}</strong>`;
  rest=rest.slice(index+path.length);
 }
 return html;
}
let current=null,generation=0;
export function stopOverview(){generation++;current?.controller?.abort();current=null;}
export async function saveOverview(){return current?.save();}
export async function mountOverview(root,boot,onDirty){
 const gen=++generation;
 let data=await api('prompt.read');if(gen!==generation)return;
 let busy=false;
 root.innerHTML=`<div class="page-head"><div><h1>概况</h1><div class="subtitle">将提示词和参考图片发给 Codex 等制作 Agent，项目进展在工作链中查看。</div></div></div>
 <div class="overview-layout"><section class="panel overview-prompt"><div class="panel-head"><div><h2>给制作 Agent 的提示词</h2><p class="small muted">制作 Agent 负责 PPT 与大阶段打卡；驻留 PPTAgent 整理记录和处理管理任务。目录随当前设置带入。</p></div><button class="primary" data-prompt-action="copy">复制完整提示词</button></div>
 <div class="panel-body"><div class="overview-steps"><span>1 复制提示词</span><span>2 连同图片发给 Agent</span><span>3 由 Agent 制作并交付</span></div>
 <div id="prompt-updated" class="notice warn" hidden>随包提示词已更新，你保存的修改仍然保留。可查看最新默认内容，再决定是否采用。</div>
 <div class="actions prompt-actions"><button data-prompt-action="edit">编辑制作要求</button><button data-prompt-action="history">修改记录</button><button data-prompt-action="default" class="quiet">查看默认内容</button><span id="prompt-save-state" class="small muted"></span></div>
 <section id="prompt-edit" class="prompt-detail" hidden><label for="prompt-editor">制作要求</label><p class="small muted">保存后更新下方完整提示词，目录由当前设置自动带入。</p><textarea id="prompt-editor" class="editor" spellcheck="false"></textarea><button data-prompt-action="save">保存修改</button></section>
 <div id="prompt-full-content" class="prompt-full-content" role="region" aria-label="完整制作提示词"></div>
 <div class="actions prompt-actions"><button class="primary" data-prompt-action="copy">复制完整提示词</button></div>
 <p id="overview-message" class="small" role="status" aria-live="polite"></p>
 <section id="prompt-history" class="prompt-detail" hidden><label for="prompt-history-select">历史版本（最近 30 次）</label><select id="prompt-history-select"></select><textarea id="prompt-history-content" class="editor" readonly aria-label="历史提示词"></textarea><button data-prompt-action="restore">恢复所选版本</button></section>

 <section id="prompt-default" class="prompt-detail" hidden><h3>当前工具包的默认制作要求</h3><textarea id="prompt-default-content" class="editor" readonly aria-label="默认制作要求"></textarea><button data-prompt-action="use-default">使用默认内容</button></section>
 <div id="prompt-confirm" class="notice warn" hidden><span>这会替换当前编辑内容并保存为新版本，已有记录保留。</span><button data-prompt-action="confirm">确认替换</button><button data-prompt-action="cancel">取消</button></div>

 </div></section><aside class="overview-side"><section class="panel prompt-paths" aria-label="自动带入的目录"><div class="panel-head"><h2>自动带入的目录</h2></div><div class="panel-body"><p class="small muted">这些目录已写入完整提示词，复制时会一起带上。</p><p id="prompt-project-rule"></p><dl><dt>默认项目位置</dt><dd id="prompt-project-path"></dd><dt>工具箱程序</dt><dd id="prompt-app-path"></dd><dt>管理数据</dt><dd id="prompt-data-path"></dd></dl><a href="#/settings">修改目录设置 →</a></div></section><section class="panel"><div class="panel-head"><h2>工具箱状态</h2></div><div class="panel-body"><div id="agent-live-panel">正在读取 Agent 状态…</div><a href="#/settings?section=agent">配置制作 Agent 的 MCP →</a><p><a href="#/pptagent">配置驻留 PPTAgent 的 API →</a></p><hr><dl><dt>当前版本</dt><dd>${esc(boot.version)}</dd><dt>可用工具与指令</dt><dd>${boot.counts.enabled_tools} / ${boot.counts.tools}</dd><dt>制作 Agent 执行权限</dt><dd>${boot.settings.agent_execution_enabled?'已开启':'已关闭'}</dd><dt>新项目授权</dt><dd>${boot.settings.auto_approve_project_requests?'按设置自动批准':'需要确认'}</dd></dl><a href="#/settings">调整权限 →</a><div class="actions" style="margin-top:16px"><button data-action="doctor">环境检测</button></div></div></section>
 <section class="panel"><div class="panel-head"><h2>当前制作工具</h2></div><div class="panel-body"><strong>${esc(boot.active.source==='builtin'?'内置 PPT 制作工具':boot.active.name)}</strong><p class="small muted">${boot.active.source==='builtin'?'随软件更新':'v'+esc(boot.active.version)} · ${boot.active.enabled?'已启用':'已停用'}</p><div class="overview-links"><a href="#/skills">查看制作规则</a><a href="#/tools">浏览工具与指令</a><a href="#/updates">软件与工具包更新</a><a href="#/logs">查看运行日志</a><a href="#/docs">使用帮助</a></div></div></section>
 <section class="panel"><div class="panel-body"><strong>也可以在软件内准备项目</strong><p class="small muted">整理图片与制作要求后再交给 Agent。直接聊天制作时可跳过这一步。</p><a href="#/create">新建制作 →</a></div></section></aside></div>`;
 const q=s=>root.querySelector(s),editor=q('#prompt-editor');
 const alive=()=>gen===generation;
 const dirty=()=>editor.value!==data.content;
 function message(text,error=false){q('#overview-message').textContent=text;q('#overview-message').classList.toggle('agent-error',error);}
 function state(){onDirty(dirty());q('#prompt-save-state').textContent=dirty()?'有未保存修改':`已保存 · 版本 ${data.revision}`;}
 function paint(){editor.value=data.content;q('#prompt-full-content').innerHTML=promptMarkup(data.text,data.paths);fitEditor();state();q('#prompt-updated').hidden=!data.base_changed;q('#prompt-project-rule').textContent=data.creation_instruction;q('#prompt-project-path').textContent=data.paths.default_projects_root;q('#prompt-app-path').textContent=data.paths.toolbox_root;q('#prompt-data-path').textContent=data.paths.management_root;q('#prompt-history-select').innerHTML=data.history.map(h=>`<option value="${h.revision}">版本 ${h.revision} · ${esc(new Date(h.updated).toLocaleString())} 归档</option>`).join('');q('#prompt-history').hidden=true;q('#prompt-default').hidden=true;}
 function fitEditor(){if(q('#prompt-edit').hidden)return;editor.style.height='auto';editor.style.height=(editor.scrollHeight+editor.offsetHeight-editor.clientHeight)+'px';}
 function lock(value){busy=value;editor.readOnly=value;root.querySelectorAll('[data-prompt-action]').forEach(b=>b.disabled=value);q('#prompt-history-select').disabled=value;}
 async function save(){
  if(!dirty())return data;
  const next=await api('prompt.save',{content:editor.value,revision:data.revision,package_id:data.package_id});
  if(alive()){data=next;paint();message('修改已保存，可在修改记录中恢复。');}return next;
 }
 current={save:async()=>{if(busy)throw new Error('正在处理，请稍后重试');lock(true);try{return await save();}finally{if(alive())lock(false);}}};
 editor.addEventListener('input',()=>{fitEditor();state();q('#prompt-confirm').hidden=true;});
 async function history(){const h=await api('prompt.history',undefined,{revision:q('#prompt-history-select').value});if(alive())q('#prompt-history-content').value=h.content.replaceAll('{{production_storage}}','').trim();}
 q('#prompt-history-select').addEventListener('change',async()=>{lock(true);try{await history();}catch(e){message(e.message,true);}finally{if(alive())lock(false);}});
 let pending=null;
 root.addEventListener('click',async event=>{
  const action=event.target.closest('[data-prompt-action]')?.dataset.promptAction;if(!action||busy||!alive())return;
  lock(true);
  try{
   if(action==='edit'){q('#prompt-edit').hidden=false;fitEditor();editor.focus();}
   if(action==='save')await save();
   if(action==='copy'){
    await save();const fresh=await api('prompt.read');if(!alive())return;
    // Another window may have edited the template; copy the current saved revision.
    data=fresh;paint();
    await copy(data.text);message('完整提示词已复制，包含正文中的全部路径。');
   }
   if(action==='history'){
    if(!data.history.length){message('尚无修改记录，首次保存后会保留原版本。');return;}
    q('#prompt-history').hidden=!q('#prompt-history').hidden;if(!q('#prompt-history').hidden)await history();
   }
   if(action==='default'){const doc=await api('doc',undefined,{path:'给模型的启动指令.txt',package_id:data.package_id});if(alive()){q('#prompt-default-content').value=doc.base.replaceAll('{{production_storage}}','').trim();q('#prompt-default').hidden=false;}}
   if(action==='restore'||action==='use-default'){pending=action==='restore'?{op:'prompt.restore',restore_revision:Number(q('#prompt-history-select').value)}:{op:'prompt.default'};q('#prompt-confirm').hidden=false;}
   if(action==='cancel'){pending=null;q('#prompt-confirm').hidden=true;}
   if(action==='confirm'&&pending){const {op,...extra}=pending;const next=await api(op,{...extra,revision:data.revision,package_id:data.package_id});if(alive()){data=next;pending=null;paint();q('#prompt-confirm').hidden=true;message('已保存为新版本，原有修改记录仍可恢复。');}}
  }catch(e){if(alive())message(e.message,true);}
  finally{if(alive())lock(false);}
 },{signal:(current.controller=new AbortController()).signal});
 const resizeObserver=new ResizeObserver(fitEditor);resizeObserver.observe(root);current.controller.signal.addEventListener('abort',()=>resizeObserver.disconnect(),{once:true});
 paint();showAgentLive();
}
