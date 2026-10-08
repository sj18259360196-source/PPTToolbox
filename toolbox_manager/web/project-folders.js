import {api} from './api.js';
import {projectIndex} from './project-index.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function mountFolderActions(main,changed,getRows,options={}){
 const head=main.querySelector('.page-head,.chain-head');if(!head)return;
 const actions=document.createElement('div');actions.className='actions';actions.innerHTML=`<button data-new-folder class="primary">${options.parent?'新建子项目':'新建项目文件夹'}</button>${options.parent?'':'<button data-scan-folders>扫描文件夹</button>'}`;head.append(actions);
 const scan=actions.querySelector('[data-scan-folders]');if(scan)scan.onclick=async e=>{e.target.disabled=true;try{const r=await api('project.scan',{});await changed();const status=main.querySelector('#archive-status');if(status)status.textContent=`已识别 ${r.found.length} 个项目${r.errors.length?'，有 '+r.errors.length+' 个目录需核对':''}`;}catch(error){const status=main.querySelector('#archive-status');if(status)status.textContent=error.message;}finally{e.target.disabled=false;}};
 actions.querySelector('[data-new-folder]').onclick=async e=>{
  e.target.disabled=true;let rows;
  try{rows=(await projectIndex()).rows;}catch(error){const status=main.querySelector('#archive-status');if(status)status.textContent=error.message;return;}finally{e.target.disabled=false;}
  if(!head.isConnected)return;
  const dialog=document.createElement('dialog');dialog.className='project-editor';dialog.innerHTML=`<form class="folder-create"><h2>新建项目文件夹</h2><label>文件夹名称<input name="name" required maxlength="100" autofocus></label><label>所在项目<select name="parent"><option value="">默认项目根目录</option>${rows.filter(r=>!r.error).map(r=>`<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</select></label><p class="small muted">会创建真实文件夹和项目记录。子项目有独立的文件、工作阶段和说明。</p><p role="alert"></p><div class="actions"><button class="primary" type="submit">创建</button><button type="button" data-close>取消</button></div></form>`;
  main.append(dialog);dialog.querySelector('[name=parent]').value=options.parent||'';dialog.showModal();dialog.onclose=()=>dialog.remove();dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('[type=submit]');b.disabled=true;try{const r=await api('project.create-folder',{name:f.elements.name.value,parent:f.elements.parent.value||null});await projectIndex(true);await changed();dialog.close();location.hash='#/workbench?project='+encodeURIComponent(r.id);}catch(error){f.querySelector('[role=alert]').textContent=error.message;b.disabled=false;}};
 };
}
