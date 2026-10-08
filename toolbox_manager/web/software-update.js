import {api} from './api.js';

let host=null,timer=null,generation=0;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const busy=new Set(['checking','downloading','verifying','installing']);
const labels={idle:'尚未检查',checking:'正在检查新版本',available:'发现新版本',current:'已是当前正式版本',downloading:'正在下载安装包',verifying:'正在校验安装包',ready:'安装包已就绪',deferred:'等待任务结束后安装',installing:'正在启动安装程序',installed:'安装程序已完成',cancelled:'下载已取消',error:'更新未完成'};
const size=n=>`${(Number(n||0)/1024/1024).toFixed(1)} MB`;

export function updateHTML(s){
 const phase=s.phase||'idle',release=s.release,disabled=busy.has(phase)||phase==='deferred';
 const progress=release?.asset?.size?Math.min(100,Math.round((s.received||0)*100/release.asset.size)):0;
 let actions=`<button data-update="check" ${disabled?'disabled':''}>检查更新</button>`;
 if(release&&['available','cancelled','error'].includes(phase))actions+='<button class="primary" data-update="download">下载更新</button>';
 if(phase==='ready')actions+=`<button class="primary" data-update="install" ${s.can_install?'':'disabled'}>安装并重新打开</button>`;
 if(['downloading','verifying','deferred'].includes(phase))actions+=`<button data-update="cancel">${phase==='deferred'?'取消排队':'取消下载'}</button>`;
 return `<p><strong>${esc(labels[phase]||phase)}</strong></p><p class="small muted">当前 ${esc(s.installed_version)}${release?` · 发行版 ${esc(release.version)}`:''}</p>
 ${release?`<p class="small muted">安装包 ${size(release.asset.size)} · 签名清单已验证</p><details><summary>本次更新内容</summary><p style="white-space:pre-wrap">${esc(release.notes)}</p></details>`:''}
 ${['downloading','verifying'].includes(phase)?`<progress max="100" value="${progress}" style="width:100%" aria-label="更新下载进度"></progress><p class="small">${progress}% · ${size(s.received)} / ${size(release?.asset?.size)}</p>`:''}
 ${s.error?`<p role="alert" class="notice warn">${esc(s.error)}</p>`:''}
 ${s.blockers?.length?`<p class="notice warn">${s.blockers.map(esc).join('；')}。安装包会保留，任务结束后自动安装。</p>`:''}
 <div class="actions">${actions}</div><label class="small" style="display:flex;gap:8px;align-items:center;margin-top:16px"><input type="checkbox" data-update-auto ${s.automatic?'checked':''}>每天自动检查一次</label>
 <p class="tiny muted">只检查版本信息，下载和安装由你发起。更新不调用 Agent，也不上传项目或 API 配置。</p>
 ${!s.can_install?'<p class="small muted">当前为源码或便携预览。正式安装后可在这里完成升级。</p>':''}
 ${s.last_check?`<p class="tiny muted">上次检查 ${esc(new Date(s.last_check*1000).toLocaleString('zh-CN'))}</p>`:''}`;
}

export async function mountSoftwareUpdate(element){
 stopSoftwareUpdate();host=element;
 const current=generation;
 async function refresh(){
  if(current!==generation||!host?.isConnected)return;
  try{const state=await api('software-update.status');if(current!==generation)return;host.innerHTML=updateHTML(state);}
  catch(e){if(current===generation)host.textContent=e.message;}
  if(current===generation)timer=setTimeout(refresh,1500);
 }
 host.onclick=async e=>{
  const button=e.target.closest('[data-update]');if(!button)return;
  button.disabled=true;
  try{const state=await api(`software-update.${button.dataset.update}`,{});if(current===generation)host.innerHTML=updateHTML(state);}
  catch(error){if(current===generation){const alert=document.createElement('p');alert.setAttribute('role','alert');alert.textContent=error.message;host.append(alert);button.disabled=false;}}
 };
 host.onchange=async e=>{
  if(!e.target.matches('[data-update-auto]'))return;
  try{await api('software-update.configure',{automatic:e.target.checked});}
  catch(error){e.target.checked=!e.target.checked;const alert=document.createElement('p');alert.textContent=error.message;host.append(alert);}
 };
 await refresh();
}

export function stopSoftwareUpdate(){generation++;clearTimeout(timer);timer=null;if(host){host.onclick=null;host.onchange=null;}host=null;}
