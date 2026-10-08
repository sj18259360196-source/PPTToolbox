import {api,copy} from './api.js';
import {formatBytes} from './projects-model.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// One request per project keeps failures isolated and releases the server write lock.
export function batchDialog(main,rows,mode,onSuccess){
 const delivering=mode==='deliver',archived=mode==='archive';
 const verb=delivering?'交付并完结':archived?'归档':'恢复';
 const items=rows.map(row=>({row,status:'waiting',message:'等待处理',included:true,path:''}));
 let phase=delivering?'preparing':'ready',stopped=false,finished=0;
 const dialog=document.createElement('dialog');dialog.className='project-batch-dialog';
 dialog.setAttribute('aria-labelledby','batch-title');
 dialog.innerHTML=`<h2 id="batch-title">批量${esc(verb)}</h2><p class="small muted">${delivering?'逐项确认交付的 PPT。完成后保留成品并将项目标为已完结。':'仅更新所选项目的归档状态，项目文件保留原位。'} 父项目和子项目分别处理。</p><p data-batch-progress role="status" aria-live="polite"></p><progress aria-label="批量处理进度" max="${items.length}" value="0"></progress><div class="batch-items"></div>${delivering?'<label class="batch-confirm"><input type="checkbox" data-batch-confirm>我已核对选中的 PPT，确认交付并完结这些项目</label>':''}<div class="batch-dialog-actions"><button class="primary" data-batch-run disabled>确认${esc(verb)}</button><button data-batch-stop>停止后续</button><button data-batch-copy hidden>复制处理结果</button><button data-batch-close>取消</button></div><p class="small muted" data-batch-note></p>`;
 main.append(dialog);dialog.showModal();
 const $=s=>dialog.querySelector(s);
 const eligible=item=>item.included&&item.status==='ready'&&(!delivering||item.path);
 const result=()=>({mode,items:items.map(i=>({id:i.row.id,label:i.row.label,path:i.path,status:i.status,message:i.message}))});
 function controls(){
  const count=items.filter(eligible).length,active=['preparing','running'].includes(phase);
  $('[data-batch-run]').hidden=phase==='finished';
  $('[data-batch-run]').textContent=`确认${verb} ${count} 个项目`;
  $('[data-batch-run]').disabled=phase!=='ready'||!count||(delivering&&!$('[data-batch-confirm]').checked);
  $('[data-batch-stop]').hidden=!active;$('[data-batch-stop]').disabled=stopped;
  $('[data-batch-close]').disabled=active;$('[data-batch-close]').textContent=phase==='finished'?'关闭':'取消';
  $('[data-batch-copy]').hidden=phase!=='finished';
  if(delivering){$('[data-batch-confirm]').disabled=phase!=='ready';$('.batch-confirm').hidden=phase==='finished';}
  $('progress').value=finished;
  const success=items.filter(i=>i.status==='success').length;
  $('[data-batch-progress]').textContent=phase==='preparing'?`正在读取交付清单 ${finished} / ${items.length}`:phase==='running'?`正在${verb} ${finished} / ${items.length}`:phase==='finished'?`成功 ${success} 个 · 其余 ${items.length-success} 个，请查看逐项结果`:`已选 ${items.length} 个项目 · 可处理 ${count} 个`;
 }
 function paint(){
  $('.batch-items').innerHTML=items.map((item,index)=>{
   const editable=phase==='ready'&&item.status==='ready';
   return `<article class="batch-item" data-batch-item="${index}" data-result="${esc(item.status)}"><div class="batch-item-head"><label><input type="checkbox" data-batch-include="${index}" ${item.included?'checked':''} ${editable?'':'disabled'}><strong>${esc(item.row.label)}</strong></label><span>${esc(item.status==='success'?'成功':item.status==='error'?'未确认':item.status==='working'?'处理中':item.status==='skipped'?'已跳过':'')}</span></div><small class="project-path">${esc(item.row.work_directory||item.row.path)}</small>${delivering&&item.plan?.files?.length?`<select aria-label="${esc(item.row.label)} 的交付文件" data-batch-file="${index}" ${editable?'':'disabled'}><option value="">请选择交付的 PPT</option>${item.plan.files.map(f=>`<option value="${esc(f.path)}" ${f.path===item.path?'selected':''}>${esc(f.path)} · ${formatBytes(f.size)}</option>`).join('')}</select>`:''}<p class="batch-item-message">${esc(item.message)}</p></article>`;
  }).join('');controls();
 }
 function stop(){stopped=true;$('[data-batch-note]').textContent='当前请求返回后停止，已经完成的项目会保留结果。';controls();}
 dialog.oncancel=e=>{if(['preparing','running'].includes(phase)){e.preventDefault();stop();}};
 $('[data-batch-stop]').onclick=stop;
 $('[data-batch-close]').onclick=()=>dialog.close();
 $('[data-batch-copy]').onclick=async()=>{try{await copy(JSON.stringify(result(),null,2));$('[data-batch-note]').textContent='处理结果已复制';}catch(e){$('[data-batch-note]').textContent=e.message;}};
 dialog.onchange=e=>{
  if(e.target.matches('[data-batch-file]')){const item=items[Number(e.target.dataset.batchFile)];item.path=e.target.value;}
  if(e.target.matches('[data-batch-include]'))items[Number(e.target.dataset.batchInclude)].included=e.target.checked;
  if(delivering&&e.target.matches('[data-batch-file],[data-batch-include]'))$('[data-batch-confirm]').checked=false;
  controls();
 };
 function stopWaiting(){for(const item of items)if(['waiting','ready'].includes(item.status)){item.status='skipped';item.message='未处理，可关闭后重新选择';}}
 $('[data-batch-run]').onclick=async()=>{
  if(phase!=='ready'||$('[data-batch-run]').disabled)return;
  phase='running';finished=0;paint();
  for(const item of items){
   if(stopped||!dialog.isConnected)break;
   if(!eligible(item)){if(item.status==='ready'){item.status='skipped';item.message=item.included?'尚未选择交付文件':'本次未勾选';}finished++;paint();continue;}
   item.status='working';item.message=`正在${verb}`;paint();
   try{
    if(delivering){const file=item.plan.files.find(f=>f.path===item.path);await api('project.complete',{project:item.row.id,revision:item.plan.revision,state_revision:item.plan.state_revision,path:file.path,file_token:file.file_token,confirmed:true});}
    else if(item.row.request_id)await api('projects.request-archive',{id:item.row.request_id,revision:item.row.revision,archived});
    else await api('projects.update',{id:item.row.id,revision:item.row.metadata_revision,label:item.row.label,category:item.row.category,archived});
    item.status='success';item.message=`已${verb}`;onSuccess(item.row.id);
   }catch(error){item.status='error';item.message=`操作未确认，请核对后重试。${error.message}`;}
   finished++;if(!dialog.isConnected)return;paint();
  }
  stopWaiting();phase='finished';paint();
 };
 const closed=new Promise(resolve=>{dialog.onclose=()=>{stopped=true;dialog.remove();resolve(result());};});
 async function prepare(){
  for(const item of items){
   if(stopped||!dialog.isConnected)break;
   try{
    if(delivering&&item.row.request_id){item.status='skipped';item.message='尚未登记为项目，不能交付；不再制作时可归档申请';}
    else if(delivering){item.message='正在读取交付文件';paint();item.plan=await api('project.delivery-plan',undefined,{project:item.row.id});item.path=item.plan.selected;item.status=item.plan.status==='ready'?'ready':'skipped';item.message=item.plan.message;}
    else{item.status=!!item.row.archived===archived?'skipped':'ready';item.message=item.status==='skipped'?`已经${verb}，无需重复处理`:`等待${verb}`;}
   }catch(error){item.status='error';item.message=error.message;}
   finished++;if(!dialog.isConnected)return;paint();
  }
  if(stopped){stopWaiting();phase='finished';}else phase='ready';
  finished=0;paint();
 }
 paint();void prepare();return closed;
}
