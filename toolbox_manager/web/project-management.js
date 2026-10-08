import {api,copy} from './api.js';
import {formatBytes,localTime} from './projects-model.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export async function openProjectFile(project,path,action='open'){
 return api('project.open',{project,path,action});
}
export async function saveProjectFile(project,path){
 const response=await fetch('/api/project.file?'+new URLSearchParams({project,path}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
 if(!response.ok)throw Error((await response.json()).error||'文件下载失败');
 const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=path.split('/').at(-1);a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function storageSummary(storage){
 if(!storage)return '待统计';
 if(storage.error)return '读取失败';
 return `${storage.complete?'':'至少 '}${formatBytes(storage.bytes)}`;
}

export async function projectDialog(main,row,mode,onChange){
 const dialog=document.createElement('dialog');dialog.className='project-management-dialog';dialog.setAttribute('aria-labelledby','project-management-title');
 dialog.innerHTML=`<header><h2 id="project-management-title">${esc(row.label)}</h2><button type="button" data-close aria-label="关闭" title="关闭">×</button></header><div data-body><p>正在读取项目</p></div><p data-status role="status"></p>`;
 main.append(dialog);dialog.showModal();let saving=false;
 dialog.querySelector('[data-close]').onclick=()=>{if(!saving)dialog.close();};
 dialog.oncancel=e=>{if(saving)e.preventDefault();};
 dialog.onclose=()=>dialog.remove();
 const body=dialog.querySelector('[data-body]'),status=dialog.querySelector('[data-status]');
 const message=t=>{if(dialog.isConnected)status.textContent=t;};
 async function run(operation){
  if(saving)return;saving=true;dialog.querySelectorAll('button,select,input').forEach(b=>b.disabled=true);message('正在处理');
  try{await operation();}catch(e){message(e.message);}finally{saving=false;if(dialog.isConnected)dialog.querySelectorAll('button,select,input').forEach(b=>b.disabled=false);}
 }
 try{
  const data=await api('project.inventory',undefined,{project:row.id});if(!dialog.isConnected)return;
  if(mode==='storage'){
   body.innerHTML=`<div class="storage-total"><strong>${storageSummary(data)}</strong><span>${data.file_count} 个文件${data.excluded_children?' · 子项目另计':''}</span></div><div class="storage-bars">${data.groups.filter(g=>g.bytes).map(g=>`<span class="storage-bar ${g.id}" style="flex:${g.bytes}" title="${esc(g.label)} ${formatBytes(g.bytes)}"></span>`).join('')}</div><div class="storage-rows">${data.groups.map(g=>`<div><span>${esc(g.label)}</span><strong>${formatBytes(g.bytes)}</strong><small>${g.files} 个文件</small></div>`).join('')}</div><p class="path-block">${esc(data.root)}</p><p class="small muted">统计于 ${esc(localTime(data.scanned_at))} · 按文件大小统计</p>${data.errors.length?`<p class="error-banner">${data.errors.map(esc).join('<br>')}</p>`:''}<div class="actions"><button data-folder>打开项目文件夹</button>${data.lifecycle.status==='completed'?'<button data-cleanup>清理制作历史</button>':'<button data-complete class="primary">交付并完结</button>'}</div>${data.lifecycle.history_cleaned?'<p class="cleanup-warning">制作历史已清理，保留的成品仍可编辑。原制作流程无法恢复。</p>':''}`;
   body.querySelector('[data-folder]').onclick=()=>run(()=>openProjectFile(row.id,null,'reveal').then(()=>message('已请求打开项目文件夹')));
   const locations=document.createElement('details');locations.className='storage-locations';
   locations.innerHTML=`<summary>分类文件位置</summary>${data.groups.filter(g=>g.paths.length).map(g=>`<section><strong>${esc(g.label)}</strong>${g.paths.map(path=>`<div><code>${esc(path)}</code><button data-location="${esc(path)}" title="打开文件夹" aria-label="打开 ${esc(path)} 文件夹">↗</button></div>`).join('')}</section>`).join('')}`;
   body.querySelector('.path-block').before(locations);
   locations.querySelectorAll('[data-location]').forEach(button=>button.onclick=()=>run(()=>openProjectFile(row.id,button.dataset.location,'reveal').then(()=>message('已请求打开文件夹'))));
   body.querySelector('[data-cleanup]')?.addEventListener('click',()=>cleanupPreview());
   body.querySelector('[data-complete]')?.addEventListener('click',()=>completion(data));
  }else if(mode==='complete'){completion(data);}
  else if(mode==='cleanup'){await cleanupPreview();}
  else if(mode==='reopen'){
   body.innerHTML='<p>重新开启后可以继续制作。现有成品和文件会保留。</p><button class="primary" data-reopen>重新开启</button>';
   body.querySelector('[data-reopen]').onclick=()=>run(async()=>{await api('project.reopen',{project:row.id,revision:data.lifecycle.revision,state_revision:data.state_revision});await onChange();dialog.close();});
  }else{
   let selected=data.deliveries[0];
   const render=()=>{body.innerHTML=`<div class="delivery-dialog-list">${data.deliveries.length?data.deliveries.map((f,i)=>`<label class="delivery-choice"><input type="radio" name="delivery" value="${i}" ${f===selected?'checked':''}><span><strong>${esc(f.version)}</strong><small>${f.kind==='verified'?'工作流交付':f.kind==='owner'?'用户确认成品':'待确认'} · ${formatBytes(f.size)}</small><small>${esc(f.path)}</small></span></label>`).join(''):'<p>暂无交付成品</p>'}</div><div class="actions">${selected?'<button class="primary" data-open>打开 PPT</button><button data-reveal>打开所在文件夹</button><button data-download>另存副本</button>':''}</div>`;
    body.querySelectorAll('[name=delivery]').forEach(b=>b.onchange=()=>{selected=data.deliveries[Number(b.value)];render();});
    body.querySelector('[data-open]')?.addEventListener('click',()=>run(()=>openProjectFile(row.id,selected.path).then(()=>message('已请求打开成品'))));
    body.querySelector('[data-reveal]')?.addEventListener('click',()=>run(()=>openProjectFile(row.id,selected.path,'reveal').then(()=>message('已请求打开所在文件夹'))));
    body.querySelector('[data-download]')?.addEventListener('click',()=>run(()=>saveProjectFile(row.id,selected.path).then(()=>message('已请求保存副本'))));
   };render();
  }
  function completion(data){
   const finals=new Set(data.deliveries.map(f=>f.path));
   const files=data.files.filter(f=>f.name.toLowerCase().endsWith('.pptx')).sort((a,b)=>Number(finals.has(b.path))-Number(finals.has(a.path))||b.mtime_ns-a.mtime_ns);
   body.innerHTML=`<h3>交付并完结</h3>${files.length?`<label>保留的成品<select data-final aria-label="保留的成品">${files.map((f,i)=>`<option value="${i}">${finals.has(f.path)?'交付文件 · ':''}${esc(f.path)} · ${formatBytes(f.size)}</option>`).join('')}</select></label><p class="cleanup-warning">完结后停止原制作流程。制作历史可在空间管理中另行清理，成品 PPT、参考图和素材会保留。</p><label class="confirm-check"><input type="checkbox" data-confirm>我已检查所选 PPT，确认本次制作完结</label><button class="primary" data-finish>确认交付并完结</button>`:'<p>项目还没有 PPTX 文件，暂时无法交付。</p>'}`;
   body.querySelector('[data-finish]')?.addEventListener('click',()=>{if(!body.querySelector('[data-confirm]').checked){message('请先检查并确认所选成品');return;}run(async()=>{
    const file=files[Number(body.querySelector('[data-final]').value)];
    await api('project.complete',{project:row.id,revision:data.lifecycle.revision,state_revision:data.state_revision,path:file.path,file_token:file.file_token,confirmed:true});
    await onChange();if(!dialog.isConnected)return;
    body.innerHTML='<h3>项目已完结</h3><p>成品已保留，制作历史尚未删除。</p><button data-cleanup>查看可清理空间</button>';message('');
    body.querySelector('[data-cleanup]').onclick=()=>cleanupPreview();
   });});
  }
  async function cleanupPreview(){
   await run(async()=>{
    const plan=await api('project.cleanup-preview',{project:row.id});if(!dialog.isConnected)return;
    body.innerHTML=`<h3>清理制作历史</h3><div class="storage-total"><strong>${formatBytes(plan.bytes)}</strong><span>${plan.files} 个文件可清理</span></div><div class="storage-rows">${plan.groups.map(g=>`<div><code>${esc(g.path)}</code><strong>${formatBytes(g.bytes)}</strong><small>${g.files} 个文件</small></div>`).join('')}</div><p>保留 ${plan.preserved.map(esc).join('、')}</p><p class="path-block">${esc(plan.retained_delivery)}</p><details><summary>待清理文件示例</summary><ul class="cleanup-files">${plan.sample.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></details><p class="cleanup-warning">删除后无法恢复旧候选、渲染与制作历史，也无法恢复原 Agent 制作流程。可继续直接编辑保留的 PPT。</p>${plan.files?'<label class="confirm-check"><input type="checkbox" data-confirm-delete>确认永久删除以上制作历史</label><button class="danger" data-delete>清理制作历史</button>':'<p>没有可清理的制作历史。</p>'}`;
    message('');
    body.querySelector('[data-delete]')?.addEventListener('click',()=>{if(!body.querySelector('[data-confirm-delete]').checked){message('请先确认永久删除');return;}run(async()=>{
     const result=await api('project.cleanup',{project:row.id,token:plan.token,confirmed:true});await onChange();if(!dialog.isConnected)return;
     body.innerHTML=`<h3>${result.status==='completed'?'清理完成':'部分文件未清理'}</h3><p>已释放 ${formatBytes(result.freed_bytes)}，删除 ${result.removed_files} 个文件。</p><p>成品、参考图和素材已保留。</p>${result.error?`<p class="error-banner">${esc(result.error)}</p><button data-retry>重新检查剩余文件</button>`:''}`;
     body.querySelector('[data-retry]')?.addEventListener('click',()=>cleanupPreview());message('');
    });});
   });
  }
 }catch(e){message(e.message);body.innerHTML='';}
}

export function globalStorageDialog(main,data){
 const dialog=document.createElement('dialog');dialog.className='project-management-dialog';
 dialog.innerHTML=`<header><h2>全局存储位置</h2><button data-close aria-label="关闭">×</button></header>${(data.global||[]).map((g,i)=>`<section class="global-storage-row"><div><strong>${esc(g.label)}</strong><span>${g.complete?'':'至少 '}${formatBytes(g.bytes)}</span></div><p class="path-block">${esc(g.path)}</p><div class="actions"><button data-global-open="${esc(g.id)}">打开文件夹</button><button data-copy="${i}">复制路径</button></div></section>`).join('')||'<p>正在统计，请稍后重新查看</p>'}<p role="status"></p>`;
 main.append(dialog);dialog.showModal();dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
 dialog.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{try{await copy(data.global[Number(b.dataset.copy)].path);dialog.querySelector('[role=status]').textContent='路径已复制';}catch(e){dialog.querySelector('[role=status]').textContent=e.message;}});
 dialog.querySelectorAll('[data-global-open]').forEach(b=>b.onclick=async()=>{try{await api('storage.open',{id:b.dataset.globalOpen});dialog.querySelector('[role=status]').textContent='已请求打开文件夹';}catch(e){dialog.querySelector('[role=status]').textContent=e.message;}});
}
