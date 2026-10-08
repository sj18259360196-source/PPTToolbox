import {usageMap,usageLink,track} from './usage.js';
import {api,copy} from './api.js';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={active_scoped:'限定启用',candidate:'待验证',verified_scoped:'待启用',disabled:'已停用',needs_review:'待复核',incompatible:'版本不兼容',passed:'历史验证通过',not_run:'尚未交付',outcome_unknown:'结果待核对',awaiting_capture:'待提取',failed:'调用失败',permission_denied:'权限未通过',invalid_arguments:'参数未通过'};
let generation=0,cleanup;
export function stopLearning(){generation++;cleanup?.();cleanup=null;}
export async function mountLearning(main,{icon}){
 stopLearning();const epoch=generation;let counts={},data,projects=[],view='skills',query='',busy=false;
 const current=()=>epoch===generation;
 main.innerHTML=`<div class="learning-page"><div class="page-head"><h1>学习库</h1><button id="learning-refresh" class="icon-button" title="刷新学习库" aria-label="刷新学习库">${icon('updates')}</button></div><div id="learning-status" class="small muted" role="status">正在读取</div><div class="learning-settings"><label><input id="learning-auto" type="checkbox" disabled>收录新交付项目</label><span id="learning-path" class="small muted"></span></div><div class="learning-tabs" role="tablist" aria-label="学习库视图">${[['skills','技能'],['candidates','待提取'],['applications','复用记录']].map(([key,label],i)=>`<button role="tab" id="learning-tab-${key}" aria-controls="learning-list" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-learning-view="${key}">${label}<span></span></button>`).join('')}</div><div class="learning-toolbar"><input type="search" id="learning-query" aria-label="搜索学习库" placeholder="搜索技能或项目"><select id="learning-project" aria-label="已交付项目"><option value="">选择已交付项目</option></select><button id="learning-collect" disabled>${icon('plus')}收录项目</button></div><p id="learning-error" role="alert" hidden></p><div id="learning-list" role="tabpanel"></div></div>`;
 const $=s=>main.querySelector(s);
 cleanup=()=>{main.onclick=null;main.querySelectorAll('.learning-dialog').forEach(d=>d.remove());};
 const error=message=>{$('#learning-error').hidden=!message;$('#learning-error').textContent=message;};
 function paint(){
  $('#learning-auto').checked=data.preferences.auto_collect;
  $('#learning-auto').disabled=busy;
  $('#learning-path').textContent=data.library_directory;
  $('#learning-status').textContent=`${data.counts.active} 个启用技能 · ${data.counts.pending} 个待验证或启用 · ${data.counts.needs_review} 个待复核`;
  main.querySelectorAll('[data-learning-view]').forEach(b=>{
   const active=b.dataset.learningView===view;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;
   b.querySelector('span').textContent=data[b.dataset.learningView].length;
  });
  $('#learning-list').setAttribute('aria-labelledby','learning-tab-'+view);
  const list=data[view].filter(row=>`${row.skill_id||''} ${row.description||''} ${row.label||''} ${row.project||''}`.toLowerCase().includes(query.toLowerCase()));
  $('#learning-list').innerHTML=list.length?list.map(row=>`<article class="learning-row"><div class="learning-name"><strong>${esc(row.skill_id||row.label)}</strong><span class="learning-badge ${row.status==='active_scoped'?'active':''}">${esc(labels[row.status]||row.status)}</span></div>${row.description?`<p>${esc(row.description)}</p>`:''}<div class="small muted">${esc(row.version||row.run_id||'')}${row.project?` · ${esc(row.project)}`:''}</div>${row.reason?`<p class="learning-reason">${esc(row.reason)}</p>`:''}${view==='skills'?usageLink('skill',row.skill_id,counts[row.skill_id]):''}<div class="learning-row-actions">${view==='skills'?`<button data-learning-detail="${esc(row.skill_id)}" data-version="${esc(row.version)}">参数与记录</button>${row.stored_status!=='disabled'?`<button data-learning-disable="${esc(row.skill_id)}" data-version="${esc(row.version)}">停用</button>`:''}`:view==='candidates'?`<button data-learning-source="${esc(row.id)}" ${row.status!=='awaiting_capture'?'disabled':''}>查看来源</button>`:''}</div></article>`).join(''):`<div class="empty">${query?'没有匹配的记录':view==='skills'?'暂无提取的技能':view==='candidates'?'暂无待提取项目':'暂无技能复用记录'}</div>`;
 }
 async function load(){
  const result=await Promise.all([api('learning.status'),api('workbench.projects'),usageMap('skill')]);if(!current())return;counts=result[2];
  [data,projects]=result;
  const selected=$('#learning-project').value;
  $('#learning-project').innerHTML='<option value="">选择已交付项目</option>'+projects.filter(p=>p.status==='delivered').map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
  $('#learning-project').value=selected;
  $('#learning-collect').disabled=!$('#learning-project').value;paint();
 }
 function dialog(title,body){
  const d=document.createElement('dialog');d.className='learning-dialog';
  d.innerHTML=`<div class="learning-dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-close aria-label="关闭" title="关闭">${icon('close')}</button></div>${body}<p role="alert"></p>`;
  main.append(d);d.showModal();d.onclose=()=>d.remove();d.querySelector('[data-close]').onclick=()=>d.close();return d;
 }
 $('#learning-auto').onchange=async e=>{
  if(busy)return;busy=true;e.target.disabled=true;
  try{await api('learning.configure',{auto_collect:e.target.checked});if(current()){error('');await load();}}
  catch(err){if(current()){error(err.message);e.target.checked=data.preferences.auto_collect;}}
  finally{busy=false;if(current())e.target.disabled=false;}
 };
 $('#learning-query').oninput=e=>{query=e.target.value;if(data)paint();};
 $('#learning-project').onchange=e=>{$('#learning-collect').disabled=!e.target.value;};
 main.querySelector('[role=tablist]').onkeydown=e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const tabs=[...main.querySelectorAll('[data-learning-view]')],i=tabs.indexOf(document.activeElement);
  const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  view=tabs[next].dataset.learningView;paint();tabs[next].focus();
 };
 main.onclick=async e=>{
  const button=e.target.closest('button');if(!button||busy)return;
  if(button.dataset.learningView){view=button.dataset.learningView;paint();return;}
  try{
   if(button.id==='learning-refresh'){busy=true;button.disabled=true;$('#learning-auto').disabled=true;await load();if(current())error('');}
   if(button.id==='learning-collect'){
    busy=true;button.disabled=true;$('#learning-auto').disabled=true;await api('learning.collect',{project:$('#learning-project').value});
    if(current()){view='candidates';error('');await load();}
   }
   if(button.dataset.learningSource){
    busy=true;button.disabled=true;$('#learning-auto').disabled=true;const value=await api('learning.source',undefined,{id:button.dataset.learningSource});if(!current())return;
    const d=dialog(value.label,`<p class="small muted">${esc(value.paths.scene)}</p><div class="learning-object-list">${value.objects.map(o=>`<div><code>${esc(o.id)}</code><span>${esc(o.kind==='text'?o.text:'原生形状')}</span></div>`).join('')}</div><button data-copy>${icon('copy')}复制来源参数</button>`);
    d.querySelector('[data-copy]').onclick=async()=>{try{await copy(JSON.stringify(value,null,2));d.querySelector('[data-copy]').textContent='已复制';}catch(err){d.querySelector('[role=alert]').textContent=err.message;}};
   }
   if(button.dataset.learningDetail){
    const row=data.skills.find(r=>r.skill_id===button.dataset.learningDetail&&r.version===button.dataset.version);
    await track('skill',row.skill_id,'viewed');counts=await usageMap('skill');
    const uses=data.applications.filter(a=>a.skill_id===row.skill_id&&a.version===row.version);
    dialog(row.skill_id,`${usageLink('skill',row.skill_id,counts[row.skill_id])}<p>${esc(labels[row.status]||row.status)}</p><p class="small muted">${esc(row.reason)}</p><h3>适用范围</h3><pre>${esc(JSON.stringify({placement_domain:row.placement_domain,layout_assumptions:row.layout_assumptions},null,2))}</pre><h3>参数</h3><pre>${esc(JSON.stringify(row.parameters,null,2))}</pre><h3>复用记录</h3>${uses.length?uses.map(a=>`<p>${esc(a.project_id||a.project)} · ${esc(labels[a.status]||a.status)}${a.reason?`<br>${esc(a.reason)}`:''}</p>`).join(''):'<p class="small muted">暂无记录</p>'}`);
   }
   if(button.dataset.learningDisable){
    const d=dialog('停用技能',`<p>${esc(button.dataset.learningDisable)} · ${esc(button.dataset.version)}</p><button data-confirm>确认停用</button>`);
    d.querySelector('[data-confirm]').onclick=async ev=>{
     ev.target.disabled=true;
     try{await api('learning.disable',{skill_id:button.dataset.learningDisable,version:button.dataset.version});if(current()){d.close();await load();}}
     catch(err){d.querySelector('[role=alert]').textContent=err.message;ev.target.disabled=false;}
    };
   }
  }catch(err){if(current())error(err.message);}
  finally{busy=false;if(current()){button.disabled=false;$('#learning-auto').disabled=false;$('#learning-collect').disabled=!$('#learning-project').value;}}
 };
 await load();
}
