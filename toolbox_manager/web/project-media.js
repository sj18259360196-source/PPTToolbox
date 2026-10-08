import {api} from './api.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const urls=new Map();
export function clearProjectMedia(){for(const url of urls.values())URL.revokeObjectURL(url);urls.clear();}
async function preview(project,page,full=false){
 const key=JSON.stringify([project,page.path,page.modified_ns,full]);if(urls.has(key))return urls.get(key);
 const response=await fetch('/api/project.preview?'+new URLSearchParams({project,path:page.path,full:full?'1':'0'}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
 if(!response.ok)throw Error('预览读取失败');const url=URL.createObjectURL(await response.blob());urls.set(key,url);return url;
}
export function cover(row){
 if(row?.gallery?.deferred)return `<div class="project-cover"><a href="#/workbench?project=${encodeURIComponent(row.id)}" aria-label="查看 ${esc(row.label)}">查看 PPT 与工作链</a></div>`;
 const version=row?.gallery?.versions?.[0],page=version?.pages?.[0];const image=page?`<img data-cover="${esc(row.id)}" alt="${esc(row.label)} · ${esc(version.kind)}">`:'';return `<div class="project-cover">${page?`${row.lifecycle?.status==='completed'?`<button data-manage="deliveries" data-id="${esc(row.id)}" aria-label="查看 ${esc(row.label)} 成品">${image}</button>`:`<a href="#/workbench?project=${encodeURIComponent(row.id)}" aria-label="查看 ${esc(row.label)}">${image}</a>`}<span>${esc(version.kind)} · ${version.pages.length} 页</span>`:'<span>暂无页面预览</span>'}</div>`;
}
export async function hydrateCovers(main,rows){
 await Promise.allSettled([...main.querySelectorAll('[data-cover]')].map(async img=>{const row=rows.find(r=>r.id===img.dataset.cover),page=row?.gallery?.versions?.[0]?.pages?.[0];if(!page)return;try{const url=await preview(row.id,page);if(img.isConnected)img.src=url;}catch{if(img.isConnected)img.alt='预览暂不可用';}}));
}
export async function mountGallery(panel,project){
 const request=panel.dataset.request;const data=await api('project.gallery',undefined,{project});if(!panel.isConnected||panel.dataset.request!==request)return;
 panel.innerHTML=`<h2>任务与版本预览</h2>${data.versions.length?data.versions.map((v,i)=>`<section><h3>${esc(v.version)} · ${esc(v.kind)} · ${v.pages.length} 页</h3>${v.pptx?`<button data-open-ppt="${esc(v.pptx)}">打开此版本 PPT</button>`:''}<div class="page-gallery">${v.pages.map((p,j)=>`<button data-page="${i},${j}"><img alt="${esc(p.name)}"><span>${esc(p.name)}</span></button>`).join('')}</div></section>`).join(''):'<p>暂无页面预览，完成渲染后会显示在这里。</p>'}${data.limited?'<p>文件较多，当前展示已索引的预览。</p>':''}<p role="status"></p>`;
 const status=panel.querySelector('[role=status]');
 panel.querySelectorAll('[data-open-ppt]').forEach(b=>b.onclick=async()=>{try{await api('project.open',{project,path:b.dataset.openPpt});status.textContent='已请求本机程序打开';}catch(e){status.textContent=e.message;}});
 panel.querySelectorAll('[data-page]').forEach(async b=>{const [i,j]=b.dataset.page.split(',').map(Number),p=data.versions[i].pages[j];try{const url=await preview(project,p);if(b.isConnected)b.querySelector('img').src=url;}catch(e){status.textContent=e.message;}
 b.onclick=async()=>{try{const url=await preview(project,p,true);if(!b.isConnected)return;const dialog=document.createElement('dialog');dialog.className='preview-dialog';dialog.innerHTML='<button>关闭预览</button><img alt="页面预览">';dialog.querySelector('img').src=url;dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();panel.append(dialog);dialog.showModal();}catch(e){status.textContent=e.message;}};});
}
export async function mountMaterialPolicy(panel,project){
 const request=panel.dataset.request;const data=await api('material.policy',undefined,{project});if(!panel.isConnected||panel.dataset.request!==request)return;
 const fields={material_search_allowed:'联网查找素材',host_generation_allowed:'使用生成图片',reference_upload_allowed:'上传必要参考局部'};
 panel.innerHTML=`<h2>项目素材权限</h2><p>默认继承全局设置，可为此项目单独选择。</p>${Object.entries(fields).map(([k,label])=>`<label class="form-row">${label}<select data-policy="${k}"><option value="inherit">继承全局 · ${data.global_values[k]?'允许':'不允许'}</option><option value="true">允许</option><option value="false">不允许</option></select></label>`).join('')}<button class="primary">保存项目权限</button><p role="status"></p>`;
 panel.querySelectorAll('[data-policy]').forEach(s=>s.value=Object.hasOwn(data.overrides,s.dataset.policy)?String(data.overrides[s.dataset.policy]):'inherit');
 panel.querySelector('button').onclick=async()=>{const values={};panel.querySelectorAll('[data-policy]').forEach(s=>{if(s.value!=='inherit')values[s.dataset.policy]=s.value==='true';});try{await api('material.policy.save',{project,revision:data.revision,values});await mountMaterialPolicy(panel,project);panel.querySelector('[role=status]').textContent='项目权限已保存';}catch(e){panel.querySelector('[role=status]').textContent=e.message;}};
}
