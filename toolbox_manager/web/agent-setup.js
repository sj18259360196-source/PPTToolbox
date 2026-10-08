import {api,copy} from './api.js';
import {showAgentLive} from './agent-live.js';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function mountAgentSetup(root){
 if(!root)return;
 root.innerHTML=`<style>#agent-setup [hidden]{display:none!important}</style><div class="panel-head"><h2>Agent 接入</h2></div><div class="panel-body">
 <section id="agent-live-panel" aria-label="Agent 实时连接状态" style="max-height:280px;overflow:auto">正在读取连接状态…</section>
 <p>下方配置用于所选客户端。实时连接列出所有已接入的客户端；连接后仍遵循项目执行权限。</p>
 <div class="tabs" role="tablist" aria-label="接入方式"><button id="agent-mode-interface" role="tab" aria-selected="true" class="active">界面配置</button><button id="agent-mode-prompt" role="tab" aria-selected="false">提示词接入</button></div><div class="form-row"><label for="agent-host">客户端</label><select id="agent-host"><option value="codex">Codex</option><option value="cursor">Cursor</option><option value="antigravity">Antigravity</option><option value="generic">其他 MCP 客户端</option></select></div>
 <label class="field-label" for="agent-path">客户端配置文件</label><input id="agent-path" style="width:100%" aria-label="客户端配置文件">
 <div id="agent-steps" class="small" style="margin:16px 0"></div>
 <div id="agent-interface-panel" role="tabpanel" aria-labelledby="agent-mode-interface"><div style="display:flex;gap:10px;flex-wrap:wrap"><button id="agent-refresh" class="btn">检查配置</button><button id="agent-plan" class="btn">预览配置</button><button id="agent-apply" class="btn primary" hidden>确认写入</button><button id="agent-probe" class="btn">运行本机自检</button><button id="agent-copy" class="btn">复制 MCP 配置</button><button id="agent-challenge" class="btn">复制验证提示词</button></div>
 <details><summary>配置内容</summary><pre id="agent-snippet" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details>
 <p class="small muted">写入后，在客户端刷新 MCP 或重启客户端。再把验证提示词发给 Agent，回到此页检查结果。只运行本机自检时，外部 Agent 仍显示待验证。</p></div>
 <div id="agent-prompt-panel" role="tabpanel" aria-labelledby="agent-mode-prompt" hidden><h3>把接入提示词发给 Agent</h3><p class="small muted">适用于能操作本机文件和终端的 Agent。提示词包含当前安装位置、配置命令和验证步骤，生成或复制不会写入客户端配置。</p><p id="agent-prompt-note" class="small muted"></p><textarea id="agent-onboarding-text" class="editor" readonly aria-label="Agent 接入提示词" style="width:100%;min-height:250px"></textarea><div class="actions" style="margin-top:12px"><button id="agent-onboarding-copy" class="primary">复制接入提示词</button><button id="agent-onboarding-refresh">检查接入结果</button><button id="agent-onboarding-challenge">复制新的验证提示词</button></div><p class="small muted">如果客户端不能自动刷新 MCP，Agent 会提示你手动刷新。配置写入、本机自检与实际连接分别显示，不会将自检当作接入成功。</p></div><p id="agent-message" role="status" class="small muted"></p></div>`;
 const q=s=>root.querySelector(s);let state,confirmation,mode='interface',refreshId=0;
 showAgentLive();
 const savedHost=localStorage.getItem('ppt-agent-host');
 if([...q('#agent-host').options].some(o=>o.value===savedHost))q('#agent-host').value=savedHost;
 const args=()=>({host:q('#agent-host').value,...(q('#agent-path').value.trim()?{path:q('#agent-path').value.trim()}:{})});
 const message=t=>q('#agent-message').textContent=t;
 async function refresh(reset=false){
  const id=++refreshId;
  if(reset)q('#agent-path').value='';
  const next=await api('agent.status',undefined,args());if(id!==refreshId||!root.isConnected)return;state=next;
  q('#agent-path').value=state.target;q('#agent-path').disabled=state.host==='generic';
  q('#agent-plan').disabled=state.host==='generic';
  q('#agent-snippet').textContent=state.snippet;
  message(state.host==='antigravity'?'在 Antigravity 的 Settings → Customizations → Installed MCP Servers 中刷新服务，再发送验证提示词。':'');
  q('#agent-steps').innerHTML=[
   ['1 · 客户端配置',state.configured?'已写入':state.host==='generic'?'请在客户端手动配置':'待配置'],
   ['2 · 本机 MCP 自检',state.probe?'通过 · '+state.probe.tool_count+' 个工具':'未检查'],
   ['3 · 连接口令验证',state.host_verification?'通过 · '+escape(state.host_verification.client.name):'尚未完成口令验证']
  ].map(([title,value])=>`<div class="form-row"><strong>${title}</strong><span>${value}</span></div>`).join('');
  if(state.config_error)message(state.config_error);
  if(mode==='prompt')await loadPrompt();
 }
 async function loadPrompt(){
  const request=args(),id=refreshId;
  const result=await api('agent.onboarding-prompt',undefined,request);
  if(id!==refreshId||!root.isConnected||JSON.stringify(request)!==JSON.stringify(args()))return null;
  q('#agent-onboarding-text').value=result.prompt;
  q('#agent-prompt-note').textContent=result.automatic_config_supported?'Agent 可通过接入命令备份并合并工具箱配置。':'通用客户端需要 Agent 确认配置入口，无法保证自动写入。';
  return result;
 }
 function chooseMode(value){mode=value;localStorage.setItem('ppt-agent-setup-mode',value);for(const key of ['interface','prompt']){const active=key===value;q('#agent-mode-'+key).setAttribute('aria-selected',String(active));q('#agent-mode-'+key).classList.toggle('active',active);q('#agent-'+key+'-panel').hidden=!active;}if(mode==='prompt')loadPrompt().catch(e=>message(e.message));}
 q('#agent-mode-interface').onclick=()=>chooseMode('interface');q('#agent-mode-prompt').onclick=()=>chooseMode('prompt');
 const handlers={
  refresh:()=>refresh(),
  'onboarding-refresh':()=>refresh(),
  'onboarding-copy':async()=>{const result=await loadPrompt();if(!result)throw new Error('客户端选择已变化，请重新复制');await copy(result.prompt);message('接入提示词已复制，请发给能操作本机的 Agent。');},
  'onboarding-challenge':async()=>{const r=await api('agent.challenge',args());await copy(r.prompt);message('新的验证提示词已复制，10 分钟内发给 Agent。');},
  plan:async()=>{confirmation=await api('agent.plan',args());q('#agent-snippet').textContent=confirmation.snippet;q('details').open=true;q('#agent-apply').hidden=false;message('将写入 '+confirmation.target+'。已有配置会先备份，其他服务条目会保留。');},
  apply:async()=>{await api('agent.apply',{confirm_id:confirmation.confirm_id});q('#agent-apply').hidden=true;await refresh();message('配置已写入。请刷新客户端 MCP 或重启客户端，再完成验证。');},
  probe:async()=>{message('正在检查 MCP 启动、工具发现和数据目录…');await api('agent.probe',{});await refresh();message('本机自检通过。请继续验证外部 Agent。');},
  copy:async()=>{await refresh();await copy(state.snippet);message('MCP 配置已复制。');},
  challenge:async()=>{const r=await api('agent.challenge',args());await copy(r.prompt);message('验证提示词已复制，10 分钟内发给 Agent。完成后点击检查配置。');}
 };
 for(const [id,fn] of Object.entries(handlers))q('#agent-'+id).onclick=async e=>{e.target.disabled=true;try{await fn();}catch(err){message(err.message);}finally{e.target.disabled=false;}};
 q('#agent-host').onchange=async()=>{localStorage.setItem('ppt-agent-host',q('#agent-host').value);confirmation=null;q('#agent-apply').hidden=true;try{await refresh(true);}catch(e){message(e.message);}};
 q('#agent-path').oninput=()=>{refreshId++;q('#agent-onboarding-text').value='';confirmation=null;q('#agent-apply').hidden=true;};
 try{await refresh();if(localStorage.getItem('ppt-agent-setup-mode')==='prompt')chooseMode('prompt');}catch(e){message(e.message);}
}
