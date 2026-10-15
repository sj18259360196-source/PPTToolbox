import {api} from './api.js';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function productionSummary(data){
 if(data.legacy)return '沿用原项目策略';
 return (data.definitions||[]).map(field=>field.options.find(option=>option.value===data.values?.[field.key])?.label||'待核对').join(' · ');
}
export function productionValues(data){return {...Object.fromEntries((data.definitions||[]).map(field=>[field.key,field.default])),...(data.values||data.global_values||{})};}
export function productionChanged(a,b){return Object.keys({...a,...b}).some(key=>a[key]!==b[key]);}
export function productionQuery(project){return project?{project}:{};}
export async function mountGlobalProductionSettings(host,{onSaved}={}){
 host.classList.add('panel','global-production-settings');
 host.innerHTML='<div class="panel-body"><div><h2>全局制作设置</h2><p class="small muted">用于之后新建的项目。已有项目在项目内单独设置。</p></div><div data-global-production-entry></div></div>';
 await mountProductionSettings(host.querySelector('[data-global-production-entry]'),{onSaved});
}
export async function mountProductionSettings(host,{project='',onSaved}={}){
 host.classList.add('production-settings-entry');
 host.innerHTML=`<button type="button" data-production-open>${project?'制作设置':'全局制作设置'}</button><span class="small muted" data-production-summary role="status">正在读取制作设置</span>`;
 const button=host.querySelector('button'),summary=host.querySelector('[data-production-summary]');
 let data;
 async function refresh(){
  try{data=await api('production.settings',undefined,productionQuery(project));if(!host.isConnected)return;summary.textContent=productionSummary(data);button.disabled=false;}
  catch(error){data=null;if(!host.isConnected)return;summary.textContent='制作设置读取失败 · '+error.message;}
 }
 button.onclick=async()=>{button.disabled=true;await refresh();button.disabled=false;if(data&&host.isConnected)await openProductionSettings(data,{project,onSaved:async saved=>{data=saved;summary.textContent=productionSummary(saved);await onSaved?.(saved);}});};
 await refresh();
}
export async function openProductionSettings(initial,{project='',onSaved}={}){
 const dialog=document.createElement('dialog');dialog.className='production-settings-dialog';dialog.setAttribute('aria-label',project?'本项目制作设置':'全局制作设置');
 let data=initial,draft=productionValues(initial),baseline={...draft},busy=false,dirty=false;
 const global=!project;
 document.body.append(dialog);
 const beforeUnload=event=>{if(dirty){event.preventDefault();event.returnValue='';}};
 window.addEventListener('beforeunload',beforeUnload);
 const close=()=>{window.removeEventListener('beforeunload',beforeUnload);dialog.close();dialog.remove();};
 const mark=()=>{
  dirty=productionChanged(draft,baseline)||Boolean(dialog.querySelector('[data-include-completed]')?.checked);
  dialog.querySelector('[data-unsaved]').textContent=dirty?'有未保存的更改':data.legacy?'保存后将应用所选策略':'设置已保存';
 };
 function paint(){
  dialog.innerHTML=`<form method="dialog"><div class="dialog-head"><h2>${global?'全局制作设置':'本项目制作设置'}</h2><button type="button" data-close aria-label="关闭制作设置">×</button></div><p class="production-scope">${global?'仅用于之后新建的项目。已有项目继续使用各自保存的设置。':'仅修改本项目。叠图检查设置只更新审查要求，页面和素材保留；其他制作设置默认用于尚未完成部分。'}</p>${data.legacy?'<p class="production-note">此历史项目沿用原项目策略。保存后才采用下方设置。</p>':''}<div class="production-fields">${(data.definitions||[]).map(field=>`<fieldset><legend>${esc(field.label)}</legend><div class="production-options">${field.control==='switch'?`<label><input type="checkbox" role="switch" data-production-switch name="${esc(field.key)}" ${draft[field.key]==='frequent'?'checked':''}><span><strong>频繁叠图检查</strong><small>关闭时每页首次全页必查，之后按需使用。开启后每个新版本的全页与必查局部均查看叠图。</small></span></label>`:field.options.map(option=>`<label><input type="radio" name="${esc(field.key)}" value="${esc(option.value)}" ${draft[field.key]===option.value?'checked':''}><span><strong>${esc(option.label)}</strong>${option.description?`<small>${esc(option.description)}</small>`:''}</span></label>`).join('')}</div>${field.description?`<p class="small muted">${esc(field.description)}</p>`:''}</fieldset>`).join('')}</div><p class="production-note">简单线性、粗线条和规则几何图标使用原生对象，页面背景与图标分开。具体对象的明确要求优先。</p>${global?'':`<details class="production-revision"><summary>已完成部分的修订范围</summary><p class="small muted">设置变化会列入待应用记录。需要修改已完成对象时，指定对象并进入正式修订流程，原合同与旧交付保留。</p><label><input type="checkbox" data-include-completed>将指定已完成区域纳入正式修订</label><div class="production-region-list">${(data.available_regions||[]).filter(region=>region.completed).map((region,index)=>`<label><input type="checkbox" data-region-index="${index}" disabled>${esc(region.label||region.region_id)}</label>`).join('')||'<p class="small muted">当前没有可选择的已完成区域。新设置仍可用于尚未完成部分。</p>'}</div></details><div class="production-state"><span>已保存版本 ${esc(data.revision)}</span><span>工作流已应用版本 ${esc(data.applied?.revision??'尚未应用')}</span><span>${data.pending?'待应用版本 '+esc(data.pending.revision)+' · '+(data.pending.scope==='selected_completed'?'含指定已完成对象':'尚未完成部分'):'暂无待应用变更'}</span></div>${data.pending?.changed_fields?.length?`<p class="small muted">受影响设置 ${esc(data.pending.changed_fields.map(key=>(data.definitions||[]).find(f=>f.key===key)?.label||key).join('、'))}${data.pending.selected_objects?.length?' · 指定对象 '+esc(data.pending.selected_objects.map(item=>data.available_regions?.find(region=>region.slide_id===item.slide_id&&region.region_id===item.region_id)?.label||'指定区域').join('、')):''}</p>`:''}`}
 <p data-unsaved role="status"></p><p data-error class="production-error" role="alert"></p><div class="actions"><button type="button" data-reset>${global?'撤销未保存修改':'恢复当前全局默认'}</button><button type="button" data-cancel>取消</button><button type="button" data-save class="primary">保存设置</button><button type="button" data-reload hidden>重新读取服务器设置</button></div></form>`;
  dialog.querySelectorAll('[data-production-switch]').forEach(input=>input.onchange=()=>{draft[input.name]=input.checked?'frequent':'standard';mark();});
  dialog.querySelectorAll('input[type=radio]').forEach(input=>input.onchange=()=>{draft[input.name]=input.value;mark();});
  const completed=dialog.querySelector('[data-include-completed]');if(completed)completed.onchange=()=>{dialog.querySelectorAll('[data-region-index]').forEach(input=>input.disabled=!completed.checked);mark();};
  dialog.querySelector('[data-close]').onclick=cancel;
  dialog.querySelector('[data-cancel]').onclick=cancel;
  dialog.querySelector('[data-reset]').onclick=async()=>{try{draft=global?{...baseline}:{...(await api('production.settings')).values};paint();}catch(error){showError(error.message);}};
  dialog.querySelector('[data-save]').onclick=save;
  dialog.querySelector('[data-reload]').onclick=async()=>{try{data=await api('production.settings',undefined,productionQuery(project));draft=productionValues(data);baseline={...draft};paint();}catch(error){showError(error.message);}};
  mark();
 }
 function cancel(){if(busy)return;if(dirty){showError('更改尚未保存。再次点击取消将放弃本次更改。');dirty=false;dialog.querySelector('[data-cancel]').textContent='放弃更改';return;}close();}
 function showError(message){dialog.querySelector('[data-error]').textContent=message;}
 async function save(){
  if(busy)return;
  const completed=dialog.querySelector('[data-include-completed]')?.checked;
  const regions=(data.available_regions||[]).filter(region=>region.completed);
  const objects=[...dialog.querySelectorAll('[data-region-index]:checked')].map(input=>{const region=regions[Number(input.dataset.regionIndex)];return {slide_id:region.slide_id,region_id:region.region_id};});
  if(completed&&!objects.length){showError('请选择需要正式修订的已完成区域');return;}
  busy=true;dialog.querySelectorAll('button,input,textarea').forEach(node=>node.disabled=true);showError('');
  try{
   await api('production.settings.save',{...productionQuery(project),revision:data.revision,values:draft,apply_scope:completed?'selected_completed':'unfinished',selected_objects:completed?objects:[]});
   const saved=await api('production.settings',undefined,productionQuery(project));
   await onSaved?.(saved);data=saved;draft=productionValues(saved);baseline={...draft};paint();dialog.querySelector('[data-unsaved]').textContent=global?'全局设置已保存，仅用于之后新建的项目':'设置已保存，生效范围请查看版本记录';
  }catch(error){showError(error.message+'。本次更改已保留，可重新读取服务器设置后再修改。');dialog.querySelector('[data-reload]').hidden=false;}
  finally{busy=false;dialog.querySelectorAll('button,input,textarea').forEach(node=>node.disabled=false);dialog.querySelectorAll('[data-region-index]').forEach(input=>input.disabled=!dialog.querySelector('[data-include-completed]').checked);}
 }
 dialog.addEventListener('cancel',event=>{event.preventDefault();cancel();});
 dialog.addEventListener('submit',event=>event.preventDefault());
 paint();dialog.showModal();
}
