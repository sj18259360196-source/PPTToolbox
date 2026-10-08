import {api} from './api.js';
import {formatBytes} from './projects-model.js';
import {openProjectFile,saveProjectFile,projectDialog} from './project-management.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function mountProjectFiles(panel,project,delivery=false){
 const identity=panel.dataset.request;let group=delivery?'delivery':'',offset=0,serial=0;
 panel.innerHTML=`<div class="section-title"><h2>${delivery?'交付成品':'项目文件'}</h2><div class="actions"><button data-folder>打开项目文件夹</button><button data-storage>空间管理</button></div></div>${!delivery?'<select data-file-group aria-label="文件分类"><option value="">全部文件</option><option value="delivery">交付成品</option><option value="input">参考图</option><option value="assets">素材</option><option value="runs">制作历史</option><option value="workflow">工作流记录</option><option value="logs">日志</option></select>':''}<p data-path class="path-block"></p><div data-files></div><div class="file-pagination"><button data-previous>上一页</button><span data-count></span><button data-next>下一页</button></div><p data-file-status role="status"></p>${delivery?'<section id="retrospective-panel"></section>':''}`;
 const alive=()=>panel.isConnected&&panel.dataset.request===identity;
 const message=t=>{if(alive())panel.querySelector('[data-file-status]').textContent=t;};
 let current;
 const action=async fn=>{try{await fn();message('已请求本机程序打开');}catch(e){message(e.message);}};
 panel.querySelector('[data-folder]').onclick=()=>action(()=>openProjectFile(project,null,'reveal'));
 panel.querySelector('[data-storage]').onclick=()=>projectDialog(panel,{id:project,label:current?.label||'项目'},'storage',load);
 panel.querySelector('[data-file-group]')?.addEventListener('change',e=>{group=e.target.value;offset=0;load().catch(e=>message(e.message));});
 panel.querySelector('[data-previous]').onclick=()=>{offset=Math.max(0,offset-100);load().catch(e=>message(e.message));};
 panel.querySelector('[data-next]').onclick=()=>{if(current.next_offset!==null){offset=current.next_offset;load().catch(e=>message(e.message));}};
 async function load(){
  const request=++serial;const data=await api('project.files',undefined,{project,group,offset,limit:100});if(!alive()||request!==serial)return;
  current=data;panel.querySelector('[data-path]').textContent=data.root;
  panel.querySelector('[data-count]').textContent=`${data.total?offset+1:0}-${Math.min(offset+100,data.total)} / ${data.total}`;
  panel.querySelector('[data-previous]').disabled=offset===0;panel.querySelector('[data-next]').disabled=data.next_offset===null;
  panel.querySelector('[data-files]').innerHTML=data.files.length?`<div class="file-list">${data.files.map((f,i)=>`<div class="file-row"><div><strong>${esc(f.version||f.name)}</strong><small>${esc(f.path)} · ${formatBytes(f.size)}${f.kind==='unconfirmed'?' · 待确认':''}</small></div><div class="file-actions"><button data-open="${i}">打开</button><button data-reveal="${i}" title="打开所在文件夹" aria-label="打开 ${esc(f.name)} 所在文件夹">↗</button><button data-download="${i}" title="另存副本" aria-label="另存 ${esc(f.name)} 副本">↓</button></div></div>`).join('')}</div>`:'<p class="empty">暂无文件</p>';
  panel.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>action(()=>openProjectFile(project,data.files[Number(b.dataset.open)].path)));
  panel.querySelectorAll('[data-reveal]').forEach(b=>b.onclick=()=>action(()=>openProjectFile(project,data.files[Number(b.dataset.reveal)].path,'reveal')));
  panel.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>action(()=>saveProjectFile(project,data.files[Number(b.dataset.download)].path)));
  message(data.limited?'部分文件无法读取，当前清单不完整':'');
  return data;
 }
 return load();
}
