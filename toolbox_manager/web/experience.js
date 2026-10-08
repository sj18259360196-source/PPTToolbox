import {usageMap,usageLink,track} from './usage.js';
import {api,copy} from './api.js';
import {mountLearning as mountComponents,stopLearning as stopComponents} from './learning.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0;
const listHtml=items=>`<ul>${(items||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`;
export async function mountLearning(main,{icon}){
 stopLearning();const epoch=generation;let records=[],counts={},searchTimer;
 main.innerHTML=`<section class="learning-page"><div class="page-head"><h1>经验库</h1><div class="actions"><button id="experience-tasks">任务复盘</button><button id="experience-components">组件技能</button><button id="experience-refresh">刷新</button></div></div>
 <p class="muted">来源经验保留历史复盘与待验证建议。具体方法需结合当前任务验证。查看次数从启用计数后累计。</p>
 <div class="learning-toolbar"><input id="experience-query" type="search" placeholder="搜索编号、方法、问题或来源" aria-label="搜索经验"><select id="experience-filter" aria-label="经验类型"><option value="all">全部来源经验</option><option value="imported">外部导入</option><option value="history">历史复盘</option><option value="proposed">待验证建议</option></select></div>
 <p id="experience-count" role="status"></p><p id="experience-error" role="alert"></p><div id="experience-list"></div><p id="experience-storage" class="small muted"></p></section>`;
 const $=s=>main.querySelector(s);
 function paint(){
  const words=$('#experience-query').value.toLowerCase().trim().split(/\s+/).filter(Boolean),filter=$('#experience-filter').value;
  const rows=records.filter(r=>(filter==='all'||filter==='imported'&&r.external_import||filter==='history'&&!r.proposed||filter==='proposed'&&r.proposed)&&words.every(q=>JSON.stringify(r).toLowerCase().includes(q)));
  $('#experience-count').textContent=`显示 ${rows.length} / ${records.length} 条 · 外部导入 ${records.filter(r=>r.external_import).length} 条`;
  $('#experience-list').innerHTML=rows.map(r=>`<article class="learning-row"><div class="learning-name"><strong>${esc(r.id)} · ${esc(r.title)}</strong><span class="learning-badge">${r.proposed?'待验证建议':'历史复盘'}</span>${r.external_import?'<span class="learning-badge">外部导入</span>':''}</div><p>${esc(r.trigger)}</p><p class="small muted">${esc(r.source_ids.join(' · '))} · 未在本次实测</p>${usageLink('experience',r.id,counts[r.id])}<br><button data-source-experience="${esc(r.id)}">查看方法与出处</button></article>`).join('')||'<div class="empty">没有匹配的经验</div>';
 }
 async function load(){try{const r=await api('experience.list');if(epoch!==generation)return;records=r.items;counts=await usageMap('experience');if(epoch!==generation)return;paint();$('#experience-error').textContent='';$('#experience-storage').textContent=`外部导入独立保存在 ${r.storage_path}`;}catch(e){if(epoch===generation)$('#experience-error').textContent=e.message;}}
 $('#experience-query').oninput=()=>{paint();clearTimeout(searchTimer);searchTimer=setTimeout(async()=>{if(epoch!==generation||!$('#experience-query').value.trim())return;const ids=Array.from(main.querySelectorAll('[data-source-experience]')).map(b=>b.dataset.sourceExperience);await track('experience',undefined,'retrieved',{ids});},500);};$('#experience-filter').onchange=paint;$('#experience-refresh').onclick=load;
 const back=()=>{main.insertAdjacentHTML('afterbegin','<p><button id="experience-back">← 来源经验</button></p>');main.querySelector('#experience-back').onclick=()=>mountLearning(main,{icon});};
 $('#experience-tasks').onclick=async()=>{await mountTaskExperiences(main,{icon});back();};
 $('#experience-components').onclick=async()=>{stopLearning();await mountComponents(main,{icon});back();};
 $('#experience-list').onclick=async e=>{
  const id=e.target.closest('[data-source-experience]')?.dataset.sourceExperience;if(!id)return;
  try{
   const r=await api('experience.show',undefined,{id});if(epoch!==generation)return;
   await track('experience',id,'viewed');counts=await usageMap('experience');if(epoch!==generation)return;paint();
   const d=document.createElement('dialog');d.className='learning-dialog source-experience-dialog';
   const evidence=(items,failure=false)=>items.map((s,i)=>`<section class="experience-evidence"><p><strong>${esc(s.source_id)} · ${esc(s.topic)}</strong><br><span class="learning-badge">${/proposed|proposal/.test(s.reported_state)?'待验证建议':'历史记录 · 未复测'}</span> 第 ${s.line_start}–${s.line_end} 行</p><pre>${esc(s.excerpt)}</pre>${failure?'':`<button data-read-source="${i}">查看原文上下文</button><p class="small muted experience-path">归档文件 ${esc(s.file)}${s.original_path?`<br>原始文档 ${esc(s.original_path)}`:""}</p>`}</section>`).join('');
   d.innerHTML=`<div class="learning-dialog-head"><h2>${esc(r.id)} · ${esc(r.title)}</h2><button data-close aria-label="关闭">关闭</button></div><p class="learning-badge">${r.kind==='proposed_method'?'待验证建议':'历史复盘'} · 未在本次实测</p><h3>适用条件</h3><p>${esc(r.trigger)}</p><h3>具体方法</h3>${listHtml(r.actions)}<h3>验证方法</h3>${listHtml(r.verification)}<h3>限制与边界</h3>${listHtml(r.constraints)}<h3>失败与问题记录</h3><p class="small muted">以下摘录按原文中的问题关键词定位，保留原文语境；其中的建议不代表已发生的失败。</p>${r.failure_records.length?evidence(r.failure_records,true):'<p>当前条目未单独提取失败记录，可继续查看下方原文。</p>'}<h3>原文出处</h3>${evidence(r.sources)}<h3>关联工具</h3>${listHtml(r.tools.map(t=>`${t.id} · ${t.title}`))}<div data-source-reader aria-live="polite"></div><p data-detail-error role="alert"></p>`;
   main.append(d);d.showModal();d.onclose=()=>d.remove();d.querySelector('[data-close]').onclick=()=>d.close();
   async function read(s,start){
    try{
     const text=await api('experience.source',undefined,{id:s.source_id,start});if(!d.isConnected)return;await track('experience',id,'source_viewed',{source_id:s.source_id});
     const reader=d.querySelector('[data-source-reader]');
     reader.innerHTML=`<h3>${esc(text.source_id)} 原文 · 第 ${text.line_start}–${text.line_end} 行</h3><p class="small muted">原文 SHA-256 已核对 · 共 ${text.total_lines} 行</p><pre>${esc(text.lines.map(l=>`${l.line}  ${l.text}`).join('\n'))}</pre><button data-prev ${text.line_start===1?'disabled':''}>上一段</button> <button data-next ${text.line_end===text.total_lines?'disabled':''}>下一段</button>`;
     reader.scrollIntoView({block:'start'});
     reader.querySelector('[data-prev]').onclick=()=>read(s,Math.max(1,text.line_start-40));
     reader.querySelector('[data-next]').onclick=()=>read(s,text.line_end+1);
     d.querySelector('[data-detail-error]').textContent='';
    }catch(err){d.querySelector('[data-detail-error]').textContent=err.message;}
   }
   d.onclick=ev=>{const button=ev.target.closest('[data-read-source]');if(button){const s=r.sources[Number(button.dataset.readSource)];read(s,Math.max(1,s.line_start-5));}};
  }catch(err){if(epoch===generation)$('#experience-error').textContent=err.message;}
 };
 await load();
}
export function stopLearning(){generation++;stopComponents();}
async function mountTaskExperiences(main,{icon}){
 stopLearning();const epoch=generation;
 let records=[];
 main.innerHTML=`<section class="learning-page"><div class="page-head"><h1>经验库</h1><div class="actions"><button id="experience-components">组件技能</button><button id="experience-refresh" class="icon-button" aria-label="刷新" title="刷新">${icon('updates')}</button></div></div>
 <div class="learning-toolbar"><input id="experience-query" type="search" placeholder="搜索项目、指令或工具" aria-label="搜索经验"></div><p id="experience-error" role="alert"></p><div id="experience-list"></div></section>`;
 const $=s=>main.querySelector(s);
 function paint(){
  const q=$('#experience-query').value.toLowerCase();
  const rows=records.filter(r=>JSON.stringify(r).toLowerCase().includes(q));
  $('#experience-list').innerHTML=rows.map(r=>`<article class="learning-row"><div class="learning-name"><strong>${esc(r.source.label)}</strong><span class="learning-badge">已归档</span></div><p class="small muted">${esc(r.source.run_id)} · ${esc(r.audit.at(-1).at)}</p><p>${esc(r.report.worked.join('；'))}</p><button data-experience="${esc(r.source.id)}">查看经验</button></article>`).join('')||'<div class="empty">暂无已获同意的任务经验</div>';
 }
 async function load(){
  try{const result=await api('retrospective',{action:'list'});if(epoch!==generation)return;records=result.items;paint();$('#experience-error').textContent='';}
  catch(e){if(epoch===generation)$('#experience-error').textContent=e.message;}
 }
 $('#experience-query').oninput=paint;
 $('#experience-refresh').onclick=load;
 $('#experience-components').onclick=async()=>{stopLearning();try{await mountComponents(main,{icon});main.insertAdjacentHTML('afterbegin','<p><a href="#/learning" id="back-experiences">← 项目经验</a></p>');main.querySelector('#back-experiences').onclick=e=>{e.preventDefault();mountLearning(main,{icon})};}catch(e){main.textContent=e.message;}};
 $('#experience-list').onclick=e=>{
  const id=e.target.closest('[data-experience]')?.dataset.experience;if(!id)return;
  const r=records.find(x=>x.source.id===id),d=document.createElement('dialog');d.className='learning-dialog';
  const labels={instructions:'有效指令',tool_steps:'工具调用过程',decisions:'决策依据',graphics:'图形使用与绘制',image_generation:'图片生成',worked:'做得好的地方',failed:'问题与失败',improvements:'改进提案 · 尚未应用',evidence:'证据',applicability:'适用范围'};
  d.innerHTML=`<div class="learning-dialog-head"><h2>${esc(r.source.label)}</h2><button data-close class="icon-button" title="关闭" aria-label="关闭">${icon('close')}</button></div><p>${esc(r.consent.user_reply)}</p>${Object.entries(labels).map(([k,label])=>r.report[k]?.length?`<h3>${label}</h3><ul>${r.report[k].map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:'').join('')}<p class="small muted">${esc(r.markdown_path)}</p><button data-copy>复制文档路径</button><p role="status"></p>`;
  main.append(d);d.showModal();d.onclose=()=>d.remove();d.querySelector('[data-close]').onclick=()=>d.close();
  d.querySelector('[data-copy]').onclick=async()=>{try{await copy(r.markdown_path);d.querySelector('[role=status]').textContent='已复制';}catch(err){d.querySelector('[role=status]').textContent=err.message;}};
 };
 await load();
}
