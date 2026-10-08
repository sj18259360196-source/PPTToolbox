import {api,copy,download} from './api.js';
import {projectIndex} from './project-index.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0,urls=[];
export function stopPreparation(){generation++;urls.forEach(URL.revokeObjectURL);urls=[];}
const read=f=>new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(Error('读取图片失败'));r.readAsDataURL(f)});
export async function mountPreparation(main,boot){
 stopPreparation();const epoch=generation;
 let row=null,busy=false,step=1;
 const id=new URLSearchParams(location.hash.split('?')[1]||'').get('id');
 if(id){row=await api('preparation.get',undefined,{id});step=row.ready?3:2;}
 const current=()=>epoch===generation;
 const error=t=>{if(current())main.querySelector('#prep-error').textContent=t};
 async function run(fn){if(busy)return;busy=true;main.querySelectorAll('button,input,textarea').forEach(x=>x.disabled=true);try{await fn()}catch(e){error(e.message)}finally{busy=false;if(current())main.querySelectorAll('button,input,textarea').forEach(x=>x.disabled=false)}}
 async function save(fields){row=await api('preparation.update',{id:row.id,revision:row.revision,...fields})}
 async function paint(){
  if(!current())return;
  main.innerHTML=`<section class="creation"><div class="page-head"><div><a href="#/projects" class="back-link">← 返回项目</a><h1>${row?esc(row.name):'新建制作'}</h1><p class="subtitle">图片另存原始副本，制作指令使用保存后的完整路径。</p></div>${row?`<button id="prep-archive">${row.archived?'恢复项目':'归档准备任务'}</button>`:''}</div><div class="creation-steps"><span class="${step===1?'active':''}">1 项目位置</span><span class="${step===2?'active':''}">2 图片与要求</span><span class="${step===3?'active':''}">3 交给 Agent</span></div><p id="prep-error" role="alert"></p><section class="panel panel-body" id="prep-body"></section></section>`;
  const body=main.querySelector('#prep-body');
  if(step===1){body.innerHTML=`<label>项目名称<input id="prep-name" maxlength="100" placeholder="例如湿地生态修复技术路线"></label><label>项目根目录<input id="prep-root" value="${esc(boot.storage.default_projects_root)}"></label><div class="actions"><button id="prep-pick">选择目录</button><a href="#/settings">修改默认位置</a></div><p class="small muted">将在所选位置新建独立工作区。已有项目和文件保持原位。</p><button class="primary" id="prep-create">创建并添加图片</button>`;
   body.querySelector('#prep-pick').onclick=()=>run(async()=>{const r=await api('storage.pick-directory',{field:'projects_directory',initial:body.querySelector('#prep-root').value});if(current()&&!r.cancelled)body.querySelector('#prep-root').value=r.path});
   body.querySelector('#prep-create').onclick=()=>run(async()=>{const name=body.querySelector('#prep-name').value.trim(),root=body.querySelector('#prep-root').value.trim();if(!name)throw Error('请填写项目名称');const signature=JSON.stringify([name,root]);let saved=JSON.parse(sessionStorage.getItem('preparation-create')||'null');if(!saved||saved.signature!==signature){saved={signature,id:crypto.randomUUID().replaceAll('-','')};sessionStorage.setItem('preparation-create',JSON.stringify(saved))}row=await api('preparation.create',{id:saved.id,name,root});sessionStorage.removeItem('preparation-create');if(!current())return;history.replaceState(null,'','#/create?id='+row.id);step=2;await paint()});
  }else if(step===2){
   body.innerHTML=`<div class="drop-zone" id="prep-drop"><strong>拖入参考图片，或点击选择</strong><input id="prep-files" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="导入参考图片"><small>PNG、JPEG、WebP，每张不超过 20 MB，最多 30 张</small></div><p class="small muted">已保存 ${row.inputs.length} 张 · 移除仅调整任务清单，不删除磁盘副本。</p><div id="prep-images">${row.inputs.map((f,i)=>`<div class="prep-image"><img data-file="${f.id}" alt="${esc(f.name)}"><div class="grow"><strong>${esc(f.saved_name)}</strong><small>${f.width} × ${f.height} · ${(f.size/1024).toFixed(1)} KB</small></div><button data-move="${i}" data-delta="-1" aria-label="上移${esc(f.saved_name)}" ${i===0?'disabled':''}>↑</button><button data-move="${i}" data-delta="1" aria-label="下移${esc(f.saved_name)}" ${i===row.inputs.length-1?'disabled':''}>↓</button><button data-remove="${i}">移除</button></div>`).join('')}</div><label>制作要求<textarea id="prep-requirements" maxlength="16000" placeholder="说明需要保留的文字、布局和可编辑要求">${esc(row.requirements)}</textarea></label><label>分类<input id="prep-category" maxlength="48" value="${esc(row.category)}"></label><div class="path-block">${esc(row.workspace)}<br>图片保存到 input，工作流使用 project 子目录。</div><div class="actions"><button id="prep-save">保存草稿</button><button class="primary" id="prep-ready">保存并查看制作指令</button></div>`;
   const fields=()=>({requirements:body.querySelector('#prep-requirements').value,category:body.querySelector('#prep-category').value});
   const uploadFiles=files=>run(async()=>{await save(fields());const messages=[];for(const f of files){try{if(f.size>20*1024*1024)throw Error('超过 20 MB');row=await api('preparation.upload',{id:row.id,revision:row.revision,name:f.name,data:await read(f)})}catch(e){messages.push(f.name+' · '+e.message)}}await paint();error(messages.join('\n'))});
   body.querySelector('#prep-files').onchange=e=>uploadFiles([...e.target.files]);
   body.querySelector('#prep-drop').ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy'};
   body.querySelector('#prep-drop').ondrop=e=>{e.preventDefault();uploadFiles([...e.dataTransfer.files])};
   body.querySelector('#prep-images').onclick=e=>{const b=e.target.closest('button');if(!b)return;run(async()=>{const ids=row.inputs.map(f=>f.id);if(b.dataset.remove!==undefined)ids.splice(Number(b.dataset.remove),1);else{const i=Number(b.dataset.move),j=i+Number(b.dataset.delta);if(j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j],ids[i]]}await save({...fields(),inputs:ids,ready:false});await paint()})};
   body.querySelector('#prep-save').onclick=()=>run(async()=>{await save(fields());error('草稿已保存，可从项目页继续')});
   body.querySelector('#prep-ready').onclick=()=>run(async()=>{await save({...fields(),ready:true});step=3;await paint()});
   for(const img of body.querySelectorAll('[data-file]')){const r=await fetch('/api/preparation.image?'+new URLSearchParams({id:row.id,file:img.dataset.file}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});if(!current())return;if(r.ok){const url=URL.createObjectURL(await r.blob());urls.push(url);img.src=url}else img.alt='副本读取失败，请核对文件'}
  }else{
   const prompt=await api('preparation.prompt',undefined,{id:row.id});if(!current())return;
   body.innerHTML=`<h2>材料已保存，等待 Agent 开始</h2><p>把下方指令发给已接入的 Agent。授权与制作进度会显示在项目页；工具箱不会自行提交对话。</p><div class="path-block">${esc(prompt.project)}</div><textarea class="editor" id="prep-prompt" readonly aria-label="本次制作指令">${esc(prompt.text)}</textarea><div class="actions"><button id="prep-copy" class="primary">复制制作指令</button><button id="prep-export">导出原图与指令</button><button id="prep-edit">修改材料</button><a href="#/settings?section=agent">检查 Agent 接入</a></div><p class="small muted">指令根据当前安装、规则和目录设置实时生成。输入文件已验证存在且内容未改变。</p>`;
   body.querySelector('#prep-copy').onclick=()=>run(async()=>{await copy((await api('preparation.prompt',undefined,{id:row.id})).text);error('制作指令已复制')});
   body.querySelector('#prep-export').onclick=()=>run(async()=>{await download(await api('preparation.export',{id:row.id}));error('已导出原图与指令')});
   body.querySelector('#prep-edit').onclick=()=>{step=2;paint().catch(e=>error(e.message))};
  }
  if(row)main.querySelector('#prep-archive').onclick=()=>run(async()=>{await save({archived:!row.archived});location.hash='#/projects'});
 }
 await paint();
}

export async function mountPreparedList(main){
 const section=document.createElement('details');section.className='prepared-section';
 section.innerHTML='<summary>制作草稿</summary><div data-drafts>展开后读取已保存的准备任务</div>';main.append(section);
 let loaded=false,busy=false;
 section.addEventListener('toggle',async()=>{
 if(!section.open||loaded||busy)return;busy=true;
 try{
 const [rows,index]=await Promise.all([api('preparation.list'),projectIndex()]);const projects=index.rows;
 const pending=rows.filter(r=>!projects.some(p=>p.work_directory?.replaceAll('\\','/').toLowerCase()===r.project.replaceAll('\\','/').toLowerCase()));
 if(!section.isConnected)return;
 section.innerHTML=`<div class="section-title"><h2>制作准备</h2><a href="#/create" class="primary">＋ 新建制作</a></div>${pending.length?`<div class="prepared-grid">${pending.filter(r=>!r.archived).map(r=>`<a class="prepared-card" href="#/create?id=${r.id}"><span class="tag ${r.ready?'blue':''}">${r.ready?'等待 Agent':'草稿'}</span><h3>${esc(r.name)}</h3><p>${r.inputs.length} 张参考图 · ${esc(r.category)}</p><small>${esc(r.workspace)}</small><strong>继续制作 →</strong></a>`).join('')}</div>${pending.some(r=>r.archived)?`<details><summary>已归档准备任务</summary>${pending.filter(r=>r.archived).map(r=>`<p><a href="#/create?id=${r.id}">${esc(r.name)}</a></p>`).join('')}</details>`:''}`:'<p class="small muted">从参考图片开始，保存材料后交给 Agent 制作。</p>'}`;
 const summary=document.createElement('summary');summary.textContent=`制作草稿 ${pending.filter(r=>!r.archived).length}`;section.prepend(summary);loaded=true;
 }catch(error){if(section.isConnected)section.querySelector('[data-drafts]').textContent=error.message;}finally{busy=false;}
 });
}
