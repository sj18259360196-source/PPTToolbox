import {projectIndex,watchProjectIndex} from './project-index.js';
import {api,copy} from './api.js';
import {mountFolderActions} from './project-folders.js';
import {requestLabels,categoryLabel,stateLabel,projectItems,filterItems,localTime,formatBytes,groupedItems,managementRow} from './projects-model.js';
import {projectDialog,globalStorageDialog,openProjectFile,storageSummary} from './project-management.js';
import {batchDialog} from './project-batch.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let timer, generation=0, dispose;
export function stopProjects(){clearTimeout(timer);generation++;dispose?.();dispose=null;}
export async function mountProjects(main,bootReady){
 stopProjects();const epoch=generation;let rows=[],requests=[],query='',category='',view='active',busy=false,requestError='',review=null,requestSequence=0,sort='manual',onlyDelivery=false,storage={projects:{},global:[]},order={revision:0,ids:[]};
 const expandedGroups=new Set(),selectedProjects=new Set();let filteredIds=[];
 main.innerHTML=`<div class="projects-page"><div class="page-head"><h1>项目</h1><span id="project-connection" class="small muted" role="status">正在连接</span></div>
 <div id="project-instance" class="small muted" style="overflow-wrap:anywhere" role="status">正在读取管理实例</div>
 <div class="project-views" role="tablist" aria-label="项目视图">${[['active','项目'],['deliveries','成品'],['completed','已完结'],['pending','待授权'],['archived','已归档']].map(([v,label])=>`<button id="projects-${v}" role="tab" aria-controls="project-list" data-view="${v}" aria-selected="${v==='active'}" tabindex="${v==='active'?0:-1}">${label} <span></span></button>`).join('')}</div>
 <div class="project-toolbar"><input id="project-query" type="search" aria-label="搜索项目" placeholder="搜索项目或成品"><select id="project-category" aria-label="分类"><option value="">全部分类</option></select><select id="project-sort" aria-label="排序"><option value="manual">手动顺序</option><option value="updated">最近活动优先</option><option value="oldest">较早活动优先</option><option value="name">名称正序</option><option value="name-desc">名称倒序</option></select><label class="project-filter"><input id="project-only-delivery" type="checkbox">有成品</label><span id="project-count" class="small muted" role="status"></span></div>
 <div class="project-storage-summary"><span>点开项目查看文件与工作记录。手动顺序下，可用每行的排序菜单调整同级项目。</span><div><button data-global-storage>查看存储</button></div></div>
 <div class="project-batch-toolbar" aria-label="批量管理"><label><input id="project-select-all" type="checkbox">全选当前结果</label><button data-selection="invert">反选</button><button data-selection="clear">清空</button><span id="project-selected-count" role="status">已选 0 个</span><div class="batch-toolbar-actions"><button data-batch="archive">批量归档</button><button data-batch="restore">批量恢复</button><button class="primary" data-batch="deliver">批量交付</button></div><small>全选包含筛选结果中的子项目。单独勾选父项目不会连选子项目。</small></div>
 <p id="archive-status" role="status"></p><p id="request-error" role="alert" hidden></p><div id="project-list" role="tabpanel" aria-labelledby="projects-active">正在读取项目</div></div>`;
 const $=s=>main.querySelector(s);
 dispose=()=>{main.onclick=null;main.onchange=null;main.querySelectorAll('dialog').forEach(d=>{if(d.classList.contains('project-batch-dialog'))d.close();else d.onclose=null;d.remove();});};
 const statusText={...requestLabels,started:'已启动'};
 const signature=r=>JSON.stringify([r.id,r.revision,r.status,r.path,r.input_roots,r.label,r.archived]);
 function validateRequests(value){
  if(!Array.isArray(value)||value.some(r=>!r||typeof r.id!=='string'||!r.id||typeof r.label!=='string'||typeof r.path!=='string'||!r.path||!Array.isArray(r.input_roots)||r.input_roots.some(p=>typeof p!=='string'||!p)||!Object.hasOwn(statusText,r.status)||!Number.isSafeInteger(r.revision)||r.revision<0)||new Set(value.map(r=>r.id)).size!==value.length)throw new Error('授权接口返回格式不兼容，请更新并重启当前管理器');
  return value;
 }
 function paintRequests(){
  $('#request-error').textContent=requestError;
  $('#request-error').hidden=!requestError;
  if(!busy)paint();
  if(review&&!review.sending){
   const current=requests.find(r=>r.id===review.row.id);
   if(requestError||!current||signature(current)!==signature(review.row)){
    review.invalid=true;review.dialog.querySelector('[role=alert]').textContent=requestError||'请求已变更，请关闭后重新查看权限';
    review.dialog.querySelectorAll('[data-decision]').forEach(b=>b.disabled=true);
   }
  }
 }
 async function readRequests(){
  const sequence=++requestSequence;
  try{const next=validateRequests(await api('projects.requests'));if(epoch!==generation||sequence!==requestSequence)return;requests=next;requestError='';}
  catch(e){if(epoch!==generation||sequence!==requestSequence)return;requestError=`授权请求读取失败。当前管理器可能不支持此接口，请核对错误与实例信息。${e.message}`;}
  if(epoch===generation)paintRequests();
 }
 async function readInstance(){
  try{const info=await bootReady;if(epoch!==generation)return;
   if(!info||typeof info.app_dir!=='string'||typeof info.data_dir!=='string')throw new Error('管理实例信息不兼容');
   const instance=info.instance;
   $('#project-instance').innerHTML=`<div class="project-root">默认保存位置 <span id="project-save-location">${esc(info.storage?.default_projects_root||info.settings?.projects_directory||'未设置')}</span></div><details id="project-diagnostics"><summary>实例信息</summary><div>当前实例 <span>${esc(instance?.id||'未提供')}</span>${instance?.mode?` · ${esc(instance.mode)}`:''}</div><div>当前服务 <span>${esc(location.origin)}</span></div><div>管理器 ${esc(info.version)} · API ${esc(info.api_version)}</div><div>程序目录 <span>${esc(instance?.app_dir||info.app_dir)}</span></div><div>管理数据 <span>${esc(instance?.data_dir||info.data_dir)}</span></div></details>`;
  }catch(e){if(epoch===generation)$('#project-instance').textContent=`管理实例读取失败。${e.message}`;}
 }
 function inspectRequest(row){
  const dialog=document.createElement('dialog');dialog.className='project-editor';dialog.setAttribute('aria-labelledby','request-dialog-title');dialog.style.cssText='max-height:calc(100dvh - 32px);overflow:auto;overflow-wrap:anywhere';
  const pending=row.status==='awaiting_authorization'&&!row.archived;
  dialog.innerHTML=`<form><h2 id="request-dialog-title">项目权限确认</h2><strong>${esc(row.label)}</strong><p>${row.archived?'已归档申请 · ' : ''}${esc(statusText[row.status])}</p>${row.archived?'<p>需要继续制作时，先在项目列表恢复申请。</p>':''}<dl><dt>项目路径</dt><dd style="margin:8px 0;white-space:pre-wrap">${esc(row.path)}</dd><dt>输入目录</dt>${row.input_roots.length?row.input_roots.map(p=>`<dd style="margin:8px 0;white-space:pre-wrap">${esc(p)}</dd>`).join(''):'<dd>无</dd>'}<dt>请求修订</dt><dd>${esc(row.revision)}</dd><dt>请求原因</dt><dd>${esc(row.reason||'未提供')}</dd></dl><p>批准仅授权本次请求列出的路径，不会启动 Office，也不会开启全局执行。批准后仍需 Agent 重试。</p>${pending?'<label><input type="checkbox" name="confirmed" required>我已核对项目路径和全部输入目录，确认提交以下决定</label>':''}<p role="alert"></p><div class="actions" style="flex-wrap:wrap">${pending?'<button type="submit" data-decision="approve" disabled>确认批准</button><button type="submit" data-decision="reject" disabled>确认拒绝</button>':''}<button type="button" data-cancel>关闭</button></div></form>`;
  const state={row,dialog,invalid:false,sending:false};review=state;
  main.append(dialog);dialog.showModal();
  dialog.onclose=()=>{if(review===state)review=null;dialog.remove();};
  dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
  dialog.oncancel=e=>{if(state.sending)e.preventDefault();};
  if(pending)dialog.querySelector('[name=confirmed]').onchange=e=>dialog.querySelectorAll('[data-decision]').forEach(b=>b.disabled=!e.target.checked||state.invalid||state.sending);
  dialog.querySelector('form').onsubmit=async e=>{
   e.preventDefault();const decision=e.submitter?.dataset.decision;
   if(epoch!==generation||state.invalid||state.sending||!pending||!['approve','reject'].includes(decision)||!dialog.querySelector('[name=confirmed]').checked)return;
   state.sending=true;requestSequence++;dialog.querySelectorAll('button,input').forEach(b=>b.disabled=true);
   try{
    await api('projects.request-decision',{id:row.id,revision:row.revision,decision});
    if(epoch!==generation)return;
    dialog.close();await readRequests();
   }catch(err){
    if(epoch!==generation)return;
    // A failed response may still have committed. Require a fresh review, never replay it.
    state.invalid=true;dialog.querySelector('[role=alert]').textContent=`决定未确认。${err.message}。请关闭后重新查看请求状态`;dialog.querySelector('[data-cancel]').disabled=false;
    await readRequests();
   }finally{state.sending=false;}
  };
 }
 function paint(){
  const items=projectItems(rows,requests,order.ids);
  const categories=[...new Set(items.map(r=>r.category))].sort();
  $('#project-category').innerHTML='<option value="">全部分类</option>'+categories.map(c=>`<option value="${esc(c)}">${esc(categoryLabel(c))}</option>`).join('');
  if(category&&!categories.includes(category))category='';
  $('#project-category').value=category;
  main.querySelectorAll('[data-view]').forEach(button=>{
   const selected=button.dataset.view===view;
   button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
   button.querySelector('span').textContent=filterItems(items,{view:button.dataset.view}).length;
  });
  $('#project-list').setAttribute('aria-labelledby',`projects-${view}`);
  const filtered=filterItems(items,{view,query,category,sort,onlyDelivery});
  filteredIds=filtered.map(i=>i.key);
  const keys=new Set(items.map(i=>i.key));for(const id of selectedProjects)if(!keys.has(id))selectedProjects.delete(id);
  paintSelection();
  $('#project-count').textContent=`${filtered.length} 个项目`;
  const focus=document.activeElement, focusedKey=focus?.closest('[data-project-key]')?.dataset.projectKey;
  const focusedAction=['data-project-select','data-request-archive','data-archive','data-edit','data-details','data-request','data-copy-delivery','data-manage','data-open-final','data-group'].find(a=>focus?.hasAttribute(a));
  const expanded=new Set([...main.querySelectorAll('.project-details[open]')].map(d=>d.closest('[data-project-key]').dataset.projectKey));
  const menus=new Set([...main.querySelectorAll('.project-more[open]')].map(d=>d.closest('[data-project-key]').dataset.projectKey+'|'+(d.classList.contains('project-order')?'order':'more')));
  const visible=groupedItems(filtered,expandedGroups,!!query||!!category||onlyDelivery||view!=='active'||sort==='size');
  $('#project-list').innerHTML=filtered.length?`${visible.map(({item,depth,children})=>{
   const r=item.project,pending=item.requests.find(q=>q.status==='awaiting_authorization'&&!q.archived);
   const request=pending||item.requests.at(-1);
   const complete=r?.lifecycle?.status==='completed';
   const status=!r&&item.archived?'已归档申请':pending?'待授权':complete?(r.lifecycle.history_cleaned?'已完结 · 历史已清理':'已完结'):r?stateLabel(r.status):requestLabels[request.status];
   const tone=pending?'pending':r?.status==='delivered'?'done':r?.error||request?.status==='rejected'?'error':'';
   return `<article class="project-row text-project-row" style="--project-depth:${depth}" data-project-key="${esc(item.key)}"><input class="project-select" type="checkbox" data-project-select="${esc(item.key)}" aria-label="选择 ${esc(item.label)}" ${selectedProjects.has(item.key)?'checked':''} ${busy?'disabled':''}><div class="project-main"><div class="project-name">${children?`<button class="group-toggle" data-group="${esc(item.key)}" aria-expanded="${expandedGroups.has(item.key)}" aria-label="展开或收起 ${esc(item.label)} 的子项目">${expandedGroups.has(item.key)?'▾':'▸'} <small>${children}</small></button>`:''}${r?`<a href="#/workbench?project=${encodeURIComponent(r.id)}">${esc(item.label)}</a>`:`<strong>${esc(item.label)}</strong>`}</div><div class="project-path" title="${esc(item.path)}">${esc(item.path)}</div><span class="project-category">${r?esc(categoryLabel(item.category)):'未登记的启动申请'} · ${esc(localTime(r?.updated_at||request?.updated_at))}</span></div><div class="project-state"><span class="project-status ${tone}">${esc(r?.error||status)}</span></div><div class="project-actions">${sort==='manual'?`<details class="project-more project-order"><summary aria-label="调整 ${esc(item.label)} 的顺序">排序</summary><div>${[['top','移到最前'],['up','上移'],['down','下移'],['bottom','移到最后']].map(([direction,label])=>`<button data-order-move="${direction}" data-order-key="${esc(item.key)}" ${busy?'disabled':''}>${label}</button>`).join('')}</div></details>`:''}${pending?`<button class="primary" data-request="${esc(pending.id)}" ${requestError?'disabled':''}>审核授权</button>`:''}${r?`<a class="project-open" href="#/workbench?project=${encodeURIComponent(r.id)}">进入项目</a><button data-folder="${esc(r.id)}" title="在资源管理器打开" aria-label="打开 ${esc(item.label)} 文件夹">文件夹</button><details class="project-more"><summary aria-label="更多项目操作">⋯</summary><div><button data-edit="${esc(r.id)}">整理项目</button><button data-manage="storage" data-id="${esc(r.id)}">空间管理</button>${complete?`<button data-manage="reopen" data-id="${esc(r.id)}">重新开启</button>`:`<button data-manage="complete" data-id="${esc(r.id)}">交付并完结</button>`}<button data-archive="${esc(r.id)}" ${busy?'disabled':''}>${r.archived?'恢复到列表':'归档项目'}</button></div></details>`:!pending?`<button data-request="${esc(request.id)}" ${requestError?'disabled':''}>查看权限</button>`:''}${!r?`<button data-request-archive="${esc(request.id)}" ${busy?'disabled':''}>${item.archived?'恢复申请':'归档申请'}</button>`:''}</div>${item.requests.length?`<details class="project-details" ${expanded.has(item.key)?'open':''}><summary data-details="${esc(item.key)}">授权记录</summary><div class="project-detail-body">${item.requests.map(q=>`<div><span>${esc(statusText[q.status])}</span><span>${esc(localTime(q.updated_at))}</span><button data-request="${esc(q.id)}">查看权限</button></div>`).join('')}</div></details>`:''}</article>`;
  }).join('')}`:`<div class="empty">${query||category?'没有匹配的项目':view==='pending'?'没有待授权项目':view==='archived'?'暂无归档项目':'暂无项目'}</div>`;
  paintSelection();
  for(const article of main.querySelectorAll('[data-project-key]'))for(const menu of article.querySelectorAll('.project-more'))menu.open=menus.has(article.dataset.projectKey+'|'+(menu.classList.contains('project-order')?'order':'more'));
  if(focusedKey&&focusedAction){
   [...main.querySelectorAll('[data-project-key]')].find(el=>el.dataset.projectKey===focusedKey)?.querySelector(`[${focusedAction}]`)?.focus({preventScroll:true});
  }
 }
 function paintSelection(){
  const managed=projectItems(rows,requests,order.ids).map(managementRow);
  const count=filteredIds.filter(id=>selectedProjects.has(id)).length,all=$('#project-select-all');
  all.checked=filteredIds.length>0&&count===filteredIds.length;all.indeterminate=count>0&&count<filteredIds.length;all.disabled=busy||!filteredIds.length;
  $('#project-selected-count').textContent=`已选 ${selectedProjects.size} 个${selectedProjects.size>count?` · 其中 ${selectedProjects.size-count} 个不在当前筛选结果`:''}`;
  main.querySelectorAll('[data-project-select]').forEach(input=>{input.checked=selectedProjects.has(input.dataset.projectSelect);input.disabled=busy;input.closest('article').classList.toggle('is-selected',input.checked);});
  main.querySelectorAll('[data-selection]').forEach(button=>button.disabled=busy||(button.dataset.selection==='clear'?!selectedProjects.size:!filteredIds.length));
  main.querySelectorAll('[data-batch]').forEach(button=>{
   button.disabled=busy||!selectedProjects.size||(button.dataset.batch==='deliver'&&!managed.some(r=>selectedProjects.has(r.id)&&!r.request_id));
   button.hidden=button.dataset.batch==='restore'?!managed.some(r=>selectedProjects.has(r.id)&&r.archived):button.dataset.batch==='archive'&&selectedProjects.size>0&&!managed.some(r=>selectedProjects.has(r.id)&&!r.archived);
  });
 }
 function receive(value){
  if(epoch!==generation)return;
  rows=value.rows;requests=validateRequests(value.requests);order=value.order||{revision:0,ids:[]};requestError='';
  $('#project-connection').textContent='登记索引已加载';paintRequests();
 }
 async function changed(){const value=await projectIndex(true);receive(value);}
 $('#project-query').oninput=e=>{query=e.target.value;paint();};
 $('#project-category').onchange=e=>{category=e.target.value;paint();};
 $('#project-sort').onchange=e=>{sort=e.target.value;paint();};
 $('#project-only-delivery').onchange=e=>{onlyDelivery=e.target.checked;paint();};
 main.onchange=e=>{
  const input=e.target.closest('[data-project-select]');
  if(input){input.checked?selectedProjects.add(input.dataset.projectSelect):selectedProjects.delete(input.dataset.projectSelect);paintSelection();}
  if(e.target.id==='project-select-all'){for(const id of filteredIds)e.target.checked?selectedProjects.add(id):selectedProjects.delete(id);paintSelection();}
 };
 main.querySelector('[role=tablist]').onkeydown=e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const tabs=[...main.querySelectorAll('[data-view]')],index=tabs.indexOf(document.activeElement);
  const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  view=tabs[next].dataset.view;paint();tabs[next].focus();
 };
 main.onclick=async e=>{
  const move=e.target.closest('[data-order-move]');
  if(move){
   if(busy)return;const items=projectItems(rows,requests,order.ids),item=items.find(i=>i.key===move.dataset.orderKey);if(!item)return;
   const rootParent=i=>rows.some(r=>r.id===i.project?.parent_id)?i.project.parent_id:null;
   const siblings=filterItems(items,{view,query,category,sort:'manual',onlyDelivery}).filter(i=>rootParent(i)===rootParent(item));
   const index=siblings.findIndex(i=>i.key===item.key),direction=move.dataset.orderMove;
   const target=direction==='top'?siblings[0]:direction==='bottom'?siblings.at(-1):siblings[index+(direction==='up'?-1:1)];
   if(!target||target.key===item.key)return;
   busy=true;move.disabled=true;
   try{order=await api('projects.reorder',{revision:order.revision,id:item.key,relative_id:target.key,placement:['up','top'].includes(direction)?'before':'after'});if(epoch!==generation)return;$('#archive-status').textContent=`已保存 ${item.label} 的顺序`;await changed();}
   catch(err){if(epoch!==generation)return;$('#archive-status').textContent=err.message;try{await changed();}catch{}}
   finally{busy=false;if(epoch===generation)paint();}return;
  }
  const select=e.target.closest('[data-selection]');
  if(select){if(busy)return;if(select.dataset.selection==='clear')selectedProjects.clear();else for(const id of filteredIds)selectedProjects.has(id)?selectedProjects.delete(id):selectedProjects.add(id);paintSelection();return;}
  const batch=e.target.closest('[data-batch]');
  if(batch){
   if(busy||!selectedProjects.size)return;
   const chosen=projectItems(rows,requests,order.ids).map(managementRow).filter(r=>selectedProjects.has(r.id));busy=true;paintSelection();
   try{const result=await batchDialog(main,chosen,batch.dataset.batch,id=>selectedProjects.delete(id));if(epoch!==generation)return;
    const count=result.items.filter(i=>i.status==='success').length;$('#archive-status').textContent=count?`已完成 ${count} 个项目，未完成的项目保留勾选。`:'本次没有更改项目';await changed();
   }catch(err){if(epoch===generation)$('#archive-status').textContent=err.message;}
   finally{busy=false;if(epoch===generation)paint();}
   return;
  }
  if(e.target.closest('[data-global-storage]')){const button=e.target.closest('button');button.disabled=true;try{storage=await api('projects.storage');if(epoch===generation)globalStorageDialog(main,storage);}catch(err){$('#archive-status').textContent=err.message;}finally{button.disabled=false;}return;}
  if(e.target.closest('[data-storage-refresh]')){try{await changed();}catch(err){$('#archive-status').textContent=err.message;}return;}
  const group=e.target.closest('[data-group]')?.dataset.group;
  if(group){expandedGroups.has(group)?expandedGroups.delete(group):expandedGroups.add(group);paint();return;}
  const action=e.target.closest('[data-manage]');
  if(action){const row=rows.find(r=>r.id===action.dataset.id);if(row){main.querySelectorAll('.project-more[open]').forEach(d=>d.open=false);await projectDialog(main,row,action.dataset.manage,changed);}return;}
  const open=e.target.closest('[data-open-final]')?.dataset.openFinal,folder=e.target.closest('[data-folder]')?.dataset.folder;
  if(open||folder){const row=rows.find(r=>r.id===(open||folder));const finals=row?.storage?.deliveries||[],final=finals.find(f=>f.path===row?.lifecycle?.delivery)||finals[0];try{await openProjectFile(row.id,open?final.path:null,open?'open':'reveal');$('#archive-status').textContent='已请求本机程序打开';}catch(err){$('#archive-status').textContent=err.message;}return;}
  const tab=e.target.closest('[data-view]');
  if(tab){view=tab.dataset.view;paint();return;}
  const copyId=e.target.closest('[data-copy-delivery]')?.dataset.copyDelivery;
  if(copyId){const row=rows.find(r=>r.id===copyId);if(row?.delivery_directory){try{await copy(row.delivery_directory);$('#project-connection').textContent='成品路径已复制';}catch(err){$('#project-connection').textContent=err.message;}}return;}
  const requestId=e.target.closest('[data-request]')?.dataset.request;
  if(requestId){const row=requests.find(r=>r.id===requestId);if(row&&!requestError&&!review)inspectRequest(row);return;}
  const requestArchive=e.target.closest('[data-request-archive]');
  if(requestArchive){
   if(busy)return;const row=requests.find(r=>r.id===requestArchive.dataset.requestArchive);if(!row)return;
   busy=true;requestArchive.disabled=true;const archived=!row.archived;
   try{await api('projects.request-archive',{id:row.id,revision:row.revision,archived});if(epoch!==generation)return;
    selectedProjects.delete(`request:${row.id}`);$('#archive-status').textContent=archived?`已归档申请 ${row.label}，可在已归档中恢复。`:`已恢复申请 ${row.label}。`;await changed();
   }catch(err){if(epoch!==generation)return;$('#archive-status').textContent=`操作未确认。${err.message}`;try{await changed();}catch{}}
   finally{busy=false;if(epoch===generation)paint();}return;
  }
  const archiveButton=e.target.closest('[data-archive]');
  if(archiveButton){
   if(busy)return;
   const row=rows.find(r=>r.id===archiveButton.dataset.archive);if(!row||row.error)return;
   busy=true;archiveButton.disabled=true;const archived=!row.archived;
   try{
    const result=await api('projects.update',{id:row.id,revision:row.metadata_revision,label:row.label,category:row.category,archived});
    if(epoch!==generation)return;
    rows=rows.map(r=>r.id===row.id?{...r,archived,metadata_revision:result.revision}:r);
    $('#archive-status').textContent=archived?`已归档 ${row.label}，可在已归档中恢复。`:`已恢复 ${row.label}，可在未归档中查看。`;
   }catch(err){
    if(epoch!==generation)return;
    $('#archive-status').textContent=`操作未确认，正在重新读取状态。${err.message}`;
    try{rows=(await projectIndex(true)).rows;}catch{}
   }finally{busy=false;if(epoch===generation)paint();}
   return;
  }
  const id=e.target.closest('[data-edit]')?.dataset.edit;if(!id)return;
  const row=rows.find(r=>r.id===id);busy=true;
  const dialog=document.createElement('dialog');dialog.className='project-editor';dialog.innerHTML=`<form><h2>整理项目</h2><label>名称<input name="label" required maxlength="120" value="${esc(row.label)}"></label><label>分类<input name="category" required maxlength="48" value="${esc(row.category)}"></label><p class="small muted">上级项目　${esc(rows.find(r=>r.id===row.parent_id)?.label||'默认项目根目录')}。层级按真实文件夹识别。</p><label><input name="archived" type="checkbox" ${row.archived?'checked':''}>归档</label><p role="alert"></p><button type="submit">保存</button><button type="button" data-cancel>取消</button></form>`;
  main.append(dialog);dialog.showModal();
  dialog.onclose=()=>{busy=false;dialog.remove();paint();};
  dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=async ev=>{
   ev.preventDefault();const f=ev.target;f.querySelector('button').disabled=true;
   try{await api('projects.update',{id,revision:row.metadata_revision,label:f.elements.label.value,category:f.elements.category.value,archived:f.elements.archived.checked});rows=(await projectIndex(true)).rows;dialog.close();}
   catch(err){dialog.querySelector('[role=alert]').textContent=err.message;f.querySelector('button').disabled=false;}
  };
 };
 mountFolderActions(main,changed,()=>rows);
 readInstance();
 try{receive(await projectIndex());}catch(error){if(epoch===generation)$('#project-connection').textContent=error.message;}
 if(epoch===generation){const release=watchProjectIndex(receive,error=>{$('#project-connection').textContent=error.message;});const oldDispose=dispose;dispose=()=>{release();oldDispose?.();};}

}
