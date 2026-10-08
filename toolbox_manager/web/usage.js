import {api} from './api.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={experience:'经验',tool:'工具',icon:'图标',skill:'组件技能'};
const actions={retrieved:'检索返回',viewed:'查看',source_viewed:'原文查看',cited:'任务引用',call:'调用',rejected:'拦截',attempted:'尝试应用',extracted:'提取',placed:'加入项目素材',applied:'生成试用样件',delivered:'交付保留'};
const outcomes={success:'成功',failed:'失败',unknown:'结果未知',waiting:'等待处理',blocked:'被拒绝',ok:'已记录'};
const date=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'暂无记录';
let generation=0;
export function stopUsage(){generation++;}
export async function usageMap(kind){const r=await api('usage.summary',undefined,{kind});return Object.fromEntries(r.items.map(x=>[x.id,x]));}
export function usageLink(kind,id,row){
 const c=row?.counts||{};
 const text=kind==='experience'?`查看 ${c.viewed||0} · 引用 ${c.cited||0}`:kind==='tool'?`调用 ${c.call||0} · 成功 ${row?.outcomes?.success||0}`:kind==='icon'?`查看 ${c.viewed||0} · 提取 ${c.extracted||0} · 加入项目 ${c.placed||0}`:`试用 ${c.applied||0} · 交付保留 ${c.delivered||0}`;
 return `<a class="usage-link small" data-usage-link href="#/usage?kind=${kind}&id=${encodeURIComponent(id)}" title="查看使用明细">${text} · ${row?.last_used?'最近 '+esc(date(row.last_used)):Object.values(c).some(Boolean)?'时间未记录':'暂无使用记录'}</a>`;
}
export async function track(kind,id,action,extra={},eventId=crypto.randomUUID()){
 try{return await api('usage.record',{event_id:eventId,kind,id,action,...extra});}
 catch(e){let n=document.querySelector('#usage-write-notice');if(!n){n=document.createElement('p');n.id='usage-write-notice';n.setAttribute('role','status');document.querySelector('#main')?.prepend(n);}n.textContent='使用次数暂未记录，请稍后重试。'+e.message;return null;}
}
export async function mountUsage(main){
 stopUsage();const epoch=generation;const params=new URLSearchParams(location.hash.split('?')[1]||'');let data,serial=0,offset=0;
 main.innerHTML=`<section class="usage-page"><div class="page-head"><h1>使用统计</h1><button id="usage-refresh">刷新</button></div><p class="muted">统计经验、工具、图标和组件技能的使用。经验采用随阶段打卡记录，检索、查看与采用分别计数。归档后历史记录继续保留。</p><p class="small muted">结果栏对应单次工具执行。<a href="#/pptagent">PPTAgent 最近处理</a>单独查看，模型 Token 和费用在 API 服务商处核对。<a href="#/docs?path=manager_docs/USAGE_COUNTS.md">统计口径 →</a></p><div class="learning-toolbar"><select id="usage-days" aria-label="统计时间"><option value="all">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select><select id="usage-kind" aria-label="统计对象"><option value="">全部对象</option>${Object.entries(names).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select><input id="usage-id" aria-label="对象编号" placeholder="精确对象编号"><label><input id="usage-tests" type="checkbox">包含测试记录</label><button id="usage-filter">查询</button></div><p id="usage-error" role="alert"></p><p id="usage-meta"></p><div id="usage-summary"></div><h2>使用明细</h2><p id="usage-detail-note" class="small muted"></p><div id="usage-events"></div><div class="actions"><button id="usage-prev">上一页</button><button id="usage-next">下一页</button></div><p id="usage-storage" class="small muted"></p></section>`;
 const $=s=>main.querySelector(s);$('#usage-kind').value=names[params.get('kind')]?params.get('kind'):'';$('#usage-id').value=params.get('id')||'';
 function paint(){
  $('#usage-meta').textContent=`计数启用于 ${date(data.enabled_since)} · 当前范围 ${data.total_events} 条记录`;
  $('#usage-detail-note').textContent=data.history_note;
  $('#usage-storage').textContent=`统计独立保存在 ${data.storage_path}`;
  $('#usage-summary').innerHTML=data.items.length?`<div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>对象</th><th>次数</th><th>结果</th><th>最近使用</th></tr></thead><tbody>${data.items.map(r=>`<tr><td><span class="muted small">${names[r.kind]}</span><br><button data-usage-id="${esc(r.id)}" data-kind="${r.kind}">${esc(r.title||r.id)}</button>${r.title?`<div class="small muted">${esc(r.id)}</div>`:''}</td><td>${Object.entries(r.counts).map(([k,v])=>`${actions[k]||esc(k)} ${v}`).join('<br>')}</td><td>${Object.entries(r.outcomes).map(([k,v])=>`${outcomes[k]||esc(k)} ${v}`).join(' · ')||'—'}${r.avg_seconds!=null?`<br><span class="small">平均 ${r.avg_seconds.toFixed(2)} 秒</span>`:''}</td><td>${r.last_used?esc(date(r.last_used)):'时间未记录'}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">当前筛选范围暂无记录，可调整时间或查看测试记录。</div>';
  $('#usage-events').innerHTML=data.events.length?data.events.map(r=>`<details class="usage-event"><summary>${r.evidence.time_unknown?'历史时间未记录':esc(date(r.at))} · ${names[r.kind]} ${esc(r.entity)} · ${actions[r.action]} · ${outcomes[r.status]||esc(r.status)} ${r.is_test?'· 测试':''} ${r.historical?'· 历史回填':''}</summary><p>项目 ${esc(r.project||'未记录')}<br>任务 ${esc(r.task||'未记录')}<br>入口 ${esc(r.source)}${r.duration!=null?`<br>耗时 ${r.duration.toFixed(2)} 秒`:''}</p><pre>${esc(JSON.stringify(r.evidence,null,2))}</pre></details>`).join(''):'<p class="muted">暂无明细</p>';
  $('#usage-prev').disabled=offset===0;$('#usage-next').disabled=data.next_offset===null;
 }
 async function load(){const request=++serial;try{const r=await api('usage.detail',undefined,{days:$('#usage-days').value,kind:$('#usage-kind').value,id:$('#usage-id').value.trim(),include_tests:$('#usage-tests').checked,offset});if(epoch!==generation||request!==serial)return;data=r;paint();$('#usage-error').textContent='';}catch(e){if(epoch===generation)$('#usage-error').textContent=e.message;}}
 const reset=()=>{offset=0;load();};$('#usage-refresh').onclick=reset;$('#usage-filter').onclick=reset;$('#usage-days').onchange=reset;$('#usage-kind').onchange=reset;$('#usage-tests').onchange=reset;$('#usage-id').onkeydown=e=>{if(e.key==='Enter')reset();};$('#usage-prev').onclick=()=>{offset=Math.max(0,offset-100);load();};$('#usage-next').onclick=()=>{offset=data.next_offset;load();};$('#usage-summary').onclick=e=>{const b=e.target.closest('[data-usage-id]');if(b){$('#usage-kind').value=b.dataset.kind;$('#usage-id').value=b.dataset.usageId;reset();}};
 await load();
}
