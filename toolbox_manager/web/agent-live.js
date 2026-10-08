import {api} from './api.js';
import {visiblePolling} from './visible-poll.js';
const names={working:'制作 Agent 正在工作',connected:'制作 Agent 已连接',error:'制作调用未完成',offline:'制作 Agent 未连接',unknown:'制作连接读取失败'};
const compactNames={working:'制作端工作中',connected:'制作端已连接',error:'制作调用未完成',offline:'制作端未连接',unknown:'连接读取失败'};
const recoveryText={
 accepted_next_failed:'提交已保存，后续步骤失败。先查状态，不要重复提交。',
 outcome_unknown:'调用结果尚未确认。核对项目状态和回执后再处理。',
 not_dispatched:'本次请求未派发。查看参数、权限或服务状态。',
 rejected:'本次请求被拒绝。确认当前任务后修正参数。'
};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let last=null,stopPolling=null;
function paint(data){
 const badge=document.querySelector('#agent-live-badge');
 if(badge){badge.dataset.state=data.state;badge.textContent=compactNames[data.state];badge.title=data.scope||'点击查看制作 Agent 的 MCP 连接';}
 const panel=document.querySelector('#agent-live-panel');
 if(!panel)return;
 const expanded=new Set([...panel.querySelectorAll('details[open][data-call]')].map(node=>node.dataset.call));
 const rows=data.sessions||[];
 const description=data.state==='offline'?'尚未收到客户端连接。已写入配置时，请在客户端刷新 MCP。':data.state==='unknown'?'无法读取本地服务状态，稍后自动重试。':`当前有 ${data.connected_count} 个 MCP 会话接入。`;
 const clients=rows.map(row=>`<div class="agent-session"><div><strong>${esc(row.client)}</strong><span class="agent-pill" data-state="${esc(row.state)}">${names[row.state]}</span></div><p>${row.state==='working'?'正在调用':'最近调用'} ${esc(row.tool||'等待工具调用')}${row.last_call?' · '+new Date(row.last_call*1000).toLocaleTimeString():''}</p>${row.recovery&&recoveryText[row.recovery.outcome]?`<p>${esc(recoveryText[row.recovery.outcome])}</p>`:''}${row.error?`<details data-call="${esc(row.id+':'+row.last_call)}"${expanded.has(row.id+':'+row.last_call)?' open':''}><summary>调用详情</summary><p class="agent-error">${esc(row.error)}</p></details><a href="#/logs">查看运行日志</a>`:''}</div>`).join('');
 const disconnected=data.recent_disconnects?.[0];
 const recent=!rows.length&&disconnected?`<p class="muted">最近断开 ${esc(disconnected.client)}${disconnected.error?' · '+esc(disconnected.error):''}</p>`:'';
 panel.innerHTML=`<div class="agent-live-heading"><strong class="agent-pill" data-state="${data.state}">${names[data.state]}</strong><small>实时连接</small></div><p>${description}</p>${clients}${recent}<p class="small muted">这里显示制作 Agent 的 MCP 会话。驻留 PPTAgent 的 API 状态在左侧 Agent 接入页查看。</p>`;
}
export function showAgentLive(){if(last)paint(last);}
export function startAgentLive(){
 if(window.__pptDesktopVisible===undefined){
  const initial=new URLSearchParams(location.search).get('desktop_visible');
  if(initial!==null)window.__pptDesktopVisible=initial==='1';
 }
 const brand=document.querySelector('.brand');
 const caption=brand?.querySelector('small');
 if(caption){caption.id='agent-live-badge';caption.dataset.state='offline';caption.textContent='正在检查制作 Agent';}
 brand?.addEventListener('click',e=>{if(e.target.closest('#agent-live-badge')){e.preventDefault();location.hash='#/overview';}});
 stopPolling?.();
 stopPolling=visiblePolling(signal=>api('agent.live',undefined,{}, {signal}),data=>{
  last=data||{state:'unknown',sessions:[],connected_count:0};paint(last);
 });
}
