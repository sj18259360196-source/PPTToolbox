import {api} from './api.js';
import {qualityMarkup} from './quality-view.js';
const escape = v=>String(v??'未记录').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function persistentRequestId(payload){
 const content={...payload};delete content.request_id;
 const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(content)));
 const key='wb-content:'+Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
 let id=sessionStorage.getItem(key);
 if(!id){id=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem(key,id);}
 return id;
}
const projectStorageKey='ppt-toolbox.workbench.project';
function rememberedProject(){try{return localStorage.getItem(projectStorageKey)||'';}catch{return '';}}
function rememberProject(id){try{if(id)localStorage.setItem(projectStorageKey,id);else localStorage.removeItem(projectStorageKey);}catch{/* Storage can be disabled in embedded browsers. */}}
const statusLabels={awaiting_analysis:'等待分析',awaiting_revision:'等待修改',awaiting_visual_review:'等待检查',ready_to_continue:'可继续制作',ready_to_deliver:'待交付',delivered:'已交付',awaiting_office:'等待 PowerPoint',tool_failed:'工具执行失败',interrupted_operation:'操作待恢复'};
let generation=0, timer, controller, blobs=[], refreshCurrent=null, preferenceSave=Promise.resolve();
export async function refreshWorkbench(){if(refreshCurrent)await refreshCurrent();}
export function stopWorkbench(){generation++;clearTimeout(timer);controller?.abort();refreshCurrent=null;blobs.forEach(URL.revokeObjectURL);blobs=[];}
export async function mountWorkbench(main){
 stopWorkbench();
 const epoch=generation;
 let snapshot, selected=null, pageIndex=0, project='', run='', cursor='', mode='side', pair='reference', zoom=100;
 let draft=null, request=null, sending=false, staged={}, stagedIdentity=null, eventFilter='all';
 let pollSerial=0, canvasSerial=0, search='';
 await preferenceSave;
 let [projects,preferences]=await Promise.all([api('workbench.projects'),api('workbench.preferences').catch(()=>({}))]);
 const requested=new URLSearchParams(location.hash.split('?')[1]||'').get('project');
 const remembered=preferences.project||rememberedProject();
 projects=projects.filter(p=>!p.archived||p.id===requested||p.id===remembered);
 if(epoch!==generation)return;
 main.innerHTML=`<section class="wb"><header class="wb-header"><div><h1>制作工作台</h1><p id="wb-project-title">选择项目后查看页面</p></div><div class="wb-header-actions"><span id="wb-connection" role="status">连接中</span><button id="wb-refresh" type="button"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10a8 8 0 0 0-14-5L3 8M3 3v5h5M4 14a8 8 0 0 0 14 5l3-3M16 16h5v5"/></svg><span>刷新工作台</span></button></div></header>
 <div class="wb-layout"><aside class="wb-sidebar"><section class="wb-projects" aria-label="项目选择"><div class="wb-section-heading"><h2>项目</h2><span id="wb-project-count"></span></div><input id="wb-project-search" type="search" aria-label="搜索项目" placeholder="搜索项目名称" autocomplete="off"><div id="wb-project-list" role="group" aria-label="项目列表"></div></section><div class="wb-tree" aria-label="对象树"></div></aside><section class="wb-center"><div class="wb-page-controls"><label>版本<select id="wb-run" aria-label="历史版本"></select></label><label>页面<select id="wb-page" aria-label="幻灯片"></select></label><div id="wb-status" class="wb-status"></div></div><div class="wb-controls"><select id="wb-pair" aria-label="比较对象"><option value="reference">参考 / 候选</option><option value="edit">候选 / 编辑抽查</option><option value="rebuild">候选 / scene复建</option></select><select id="wb-mode" aria-label="比较模式"><option value="side">并排</option><option value="overlay">叠加</option><option value="difference">差异记录</option></select><label>缩放 <input id="wb-zoom" type="range" min="50" max="200" value="100"><output id="wb-zoom-value">100%</output></label><label><input id="wb-boxes" type="checkbox" checked>对象框</label></div><div class="wb-canvas"></div><details class="wb-image-details"><summary>图像信息</summary><div class="wb-identities"></div></details><section id="wb-request"></section></section><aside class="wb-inspector"></aside></div><details class="wb-events"><summary>操作与来源<span>查看调用和工作流记录</span></summary><div class="wb-event-tools"><label>记录范围 <select id="wb-event-filter"><option value="all">全部记录</option><option value="page">当前页</option><option value="object">当前对象</option></select></label><p id="wb-event-coverage"></p></div><div id="wb-events"></div></details></section>`;
 const $=s=>main.querySelector(s);
 $('.wb-center>.wb-controls').insertAdjacentHTML('beforebegin','<div id="wb-quality-panel"></div>');
 $('.wb-center>.wb-controls').insertAdjacentHTML('beforeend','<label><input id="wb-inspector-toggle" type="checkbox" checked>检查器</label>');
 $('#wb-pair').insertAdjacentHTML('beforeend','<option value="design">旧设计 / 新设计</option>');
 project=projects.find(p=>p.id===requested)?.id||projects.find(p=>p.id===remembered)?.id||projects[0]?.id||'';
 function saveSelection(){
  rememberProject(project);
  const chosen=project;
  preferenceSave=preferenceSave.then(()=>api('workbench.preferences.save',{project:chosen})).catch(()=>{});
  const query=new URLSearchParams(location.hash.split('?')[1]||'');
  if(project)query.set('project',project);else query.delete('project');
  history.replaceState(null,'','#/workbench'+(query.size?'?'+query:''));
 }
 const iconEntry=document.createElement('a');iconEntry.className='wb-icon-entry';iconEntry.textContent='图标素材与重绘';
 $('.wb-sidebar').prepend(iconEntry);
 function paintProjects(){
  iconEntry.href='#/icons?project='+encodeURIComponent(project);
  const visible=projects.filter(p=>p.label.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  $('#wb-project-count').textContent=search?`${visible.length} / ${projects.length}`:projects.length;
  $('#wb-project-list').innerHTML=visible.length?visible.map(p=>`<button type="button" class="wb-project${p.id===project?' selected':''}" data-project="${escape(p.id)}" aria-pressed="${p.id===project}" title="${escape(p.label)}"><span>${escape(p.label)}</span><small>${escape(p.error?'项目无法读取':statusLabels[p.status]||p.status||'状态待核对')} · ${p.archived?'已归档':p.readonly?'只读':'受控编辑'}</small></button>`).join(''):`<p class="wb-empty">${search?'没有匹配的项目':'尚无已登记项目'}</p>`;
  $('#wb-project-title').textContent=projects.find(p=>p.id===project)?.label||'选择项目后查看页面';
 }
 function resetProject(){
  $('#wb-quality-panel').textContent='';
  run='';cursor='';selected=null;draft=null;staged={};stagedIdentity=null;request=null;snapshot=null;pageIndex=0;canvasSerial++;
  blobs.forEach(URL.revokeObjectURL);blobs=[];
  $('#wb-request').textContent='';$('#wb-status').textContent='';$('#wb-run').innerHTML='';$('#wb-page').innerHTML='';$('#wb-events').innerHTML='';$('#wb-event-coverage').textContent='';$('.wb-identities').textContent='';
  $('.wb-tree').innerHTML='<h2>区域与对象</h2><p class="wb-empty">加载后显示页面对象</p>';
  $('.wb-inspector').innerHTML='<h2>对象检查器</h2><p class="wb-empty">选择页面对象后查看详情</p>';
  $('.wb-canvas').innerHTML=`<div class="wb-canvas-empty">${project?'正在加载项目…':'请先登记项目'}</div>`;
 }
 saveSelection();paintProjects();resetProject();
 const fetchJSON=async(path)=>{
  controller=new AbortController();
  const r=await fetch(path,{signal:controller.signal,headers:{Authorization:'Bearer '+(sessionStorage.getItem('ppt-manager-token')||'')}});
  const d=await r.json();if(!r.ok)throw new Error(d.error);return d.result;
 };
 async function poll(force=false){
  if(epoch!==generation)return;
  clearTimeout(timer);controller?.abort();
  const serial=++pollSerial,isCurrent=()=>epoch===generation&&serial===pollSerial;
  if(document.hidden&&!force){timer=setTimeout(poll,5000);return;}
  if(force){$('#wb-refresh').disabled=true;$('#wb-refresh span').textContent='刷新中…';$('#wb-connection').textContent='正在刷新';}
  let wanted=project,version=run;
  try{
   const current=(await api('workbench.projects')).filter(p=>!p.archived||p.id===project);
   if(!isCurrent())return;
   if(JSON.stringify(current)!==JSON.stringify(projects)){
    projects=current;
    if(!projects.some(p=>p.id===project)){project=projects[0]?.id||'';wanted=project;resetProject();version=run;saveSelection();}
    paintProjects();
   }
   if(!project){$('#wb-connection').textContent='尚无已登记项目';return;}
   const next=await fetchJSON('/api/workbench.snapshot?'+new URLSearchParams({project,...(run?{run}:{})}));
   if(!isCurrent()||wanted!==project||version!==run)return;
   $('#wb-connection').textContent='已连接 · '+new Date(next.read_at).toLocaleTimeString();
   if(force||next.cursor!==cursor){snapshot=next;cursor=next.cursor;await paint();}
   if(!isCurrent()||wanted!==project)return;
   const pending=sessionStorage.getItem('wb-request:'+project);
   if(pending){
    const r=await api('workbench.request',undefined,{project,id:pending});
    if(isCurrent()&&wanted===project&&pending===sessionStorage.getItem('wb-request:'+project)&&JSON.stringify(r)!==JSON.stringify(request)){request=r;await showRequest();}
   }
  }catch(e){if(e.name!=='AbortError'&&isCurrent())$('#wb-connection').textContent='连接中断 · '+e.message;}
  finally{if(isCurrent()){$('#wb-refresh').disabled=false;$('#wb-refresh span').textContent='刷新工作台';timer=setTimeout(poll,3000);}}
 }
 async function image(info){
  if(info?.status!=='available')return null;
  const response=await fetch('/api/workbench.artifact?'+new URLSearchParams({project,id:info.id}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
  if(!response.ok)throw new Error('图像身份已失效');
  const url=URL.createObjectURL(await response.blob());blobs.push(url);return url;
 }
 function inspect(){
  if(!snapshot?.pages[pageIndex])return;
  const obj=snapshot.pages[pageIndex].objects.find(o=>o.id===selected);
  $('.wb-inspector').innerHTML=obj?`<h2>对象检查器</h2><strong>${escape(obj.id)}</strong><p>${escape(({text:'文字',shape:'形状',path:'原生路径',image:'位图',group:'组合',line:'线条',table:'表格',chart:'数据图表',connector:'连接线'})[obj.scene.kind]||obj.scene.kind)} · ${obj.parent?'组合内对象':'独立对象'}</p>${obj.scene.kind==='image'?`<p class="wb-raster-note">${escape(obj.scene.raster_reason||'检查这部分是否应当重绘成原生对象。替换图片无法编辑内部形状。')}</p>`:''}<details><summary>场景属性</summary><pre>${escape(JSON.stringify(obj.scene,null,2))}</pre></details><details><summary>PPTX 实际读取</summary><pre>${escape(JSON.stringify(obj.pptx,null,2))}</pre></details><details><summary>Office 编辑读回</summary><pre>${obj.office.length?escape(JSON.stringify(obj.office,null,2)):'尚未进行编辑读回检查'}</pre></details>`:'<h2>对象检查器</h2><p>点击页面或对象列表，查看编辑类型和属性。</p>';
  if(obj&&!snapshot.readonly&&snapshot.pages[pageIndex].planning_state==='valid'&&window.innerWidth>=1000&&['text','shape'].includes(obj.scene.kind)&&!obj.parent){
   const value=draft?.id===obj.id?draft.values:{text:obj.scene.text||'',font_size_pt:obj.scene.style?.font_size_pt||18,
       color:obj.scene.style?.[obj.scene.kind==='text'?'color':'fill']||'000000',bbox:obj.scene.bbox};
   $('.wb-inspector').insertAdjacentHTML('afterbegin',`<form id="wb-form"><h2>编辑草稿</h2>${obj.scene.kind==='text'?`<label>纯文本<textarea name="text">${escape(value.text)}</textarea></label><label>字号 pt<input name="font_size_pt" type="number" min="1" step=".5" value="${escape(value.font_size_pt)}"></label>`:''}<label>颜色<input name="color" type="color" value="#${escape(value.color)}"></label><div class="wb-geometry">${['x','y','宽','高'].map((label,i)=>`<label>${label}<input name="b${i}" type="number" step=".5" value="${escape(value.bbox[i])}"></label>`).join('')}</div><pre id="wb-diff">无修改</pre><button type="button" id="wb-stage">加入草稿</button><button type="submit" ${sending?'disabled':''}>生成候选</button><button type="button" id="wb-discard">撤销草稿</button><p id="wb-write-status"></p></form>`);
   const form=$('#wb-form');
   if(form.elements.text)form.elements.text.setAttribute('aria-label','纯文本');
   if(form.elements.font_size_pt)form.elements.font_size_pt.setAttribute('aria-label','字号 pt');
   form.elements.color.setAttribute('aria-label','颜色');
   const compute=()=>{
    const values={text:form.elements.text?.value,font_size_pt:Number(form.elements.font_size_pt?.value),
      color:form.elements.color.value.slice(1).toUpperCase(),bbox:[0,1,2,3].map(i=>Number(form.elements['b'+i].value))};
    if(!draft||draft.id!==obj.id)draft={id:obj.id,original:structuredClone(obj.scene),identity:stagedIdentity||identity(),slide:snapshot.pages[pageIndex].id,
      region:snapshot.pages[pageIndex].regions.find(r=>obj.id.startsWith(snapshot.pages[pageIndex].id+'.'+r.id+'.'))?.id};
    draft.values=values;
    const old=draft.original,changes=[];
    if(old.kind==='text'){
     if(values.text!==old.text)changes.push({op:'text.set',id:obj.id,text:values.text});
     const style={};
     if(values.font_size_pt!==old.style?.font_size_pt)style.font_size_pt=values.font_size_pt;
     if(values.color!==old.style?.color)style.color=values.color;
     if(Object.keys(style).length)changes.push({op:'text.style',id:obj.id,style});
    }else if(values.color!==old.style?.fill)changes.push({op:'fill.set',id:obj.id,color:values.color});
    if(JSON.stringify(values.bbox)!==JSON.stringify(old.bbox))changes.push({op:'geometry.set',id:obj.id,bbox:values.bbox});
    draft.changes=changes;
    $('#wb-diff').textContent=JSON.stringify({baseline:draft.identity.revision,staged,before:old,changes},null,2);
   };
   form.oninput=compute;
   if(draft?.id===obj.id)compute();
   $('#wb-discard').onclick=()=>{draft=null;staged={};stagedIdentity=null;inspect();};
   $('#wb-stage').onclick=()=>{compute();if(draft.changes.length>1){$('#wb-write-status').textContent='同一对象每候选只允许一种操作';return;}staged[obj.id]=structuredClone(draft);stagedIdentity=draft.identity;$('#wb-write-status').textContent='已加入草稿 · '+Object.keys(staged).length+' 个对象';};
   form.onsubmit=async e=>{
    e.preventDefault();if(sending)return;compute();
    const all={...staged,[obj.id]:draft},changes=Object.values(all).flatMap(d=>d.changes);
    if(!changes.length)return;
    if(Object.values(all).some(d=>d.changes.length>1||d.region!==draft.region||d.slide!==draft.slide)){$('#wb-write-status').textContent='同一对象只允许一种操作，目标必须属于同一区域';return;}
    const payload={project,request_id:crypto.randomUUID().replaceAll('-',''),action:'generate',identity:draft.identity,
     slide:draft.slide,region:draft.region,changes,reason:'Explicit browser draft confirmed'};
    await send(payload);
   };
  }
  main.querySelectorAll('[data-object]').forEach(e=>e.classList.toggle('selected',e.dataset.object===selected));
  if(obj?.skill)$('.wb-inspector').insertAdjacentHTML('beforeend',`<h3>技能来源</h3><pre>${escape(JSON.stringify(obj.skill,null,2))}</pre>`);
  timeline();
 }
 function timeline(){
  if(!snapshot?.pages[pageIndex])return;
  const page=snapshot.pages[pageIndex],needle=eventFilter==='object'?selected:page.id;
  const matches=v=>eventFilter==='all'||Boolean(needle&&JSON.stringify(v).includes(needle));
  const trials=snapshot.trials.filter(t=>matches(t)||(eventFilter==='page'&&t.slide_index===page.index));
  const calls=new Set(trials.map(t=>t.call_id).filter(Boolean));
  const events=snapshot.events.filter(e=>matches(e)||calls.has(e.call_id));
  const history=snapshot.history.filter(matches);
  const adoptions=Object.fromEntries(Object.entries(snapshot.adoptions).filter(([,v])=>matches(v)));
  $('#wb-event-coverage').textContent=eventFilter==='all'?'仅显示已有记录，缺失的关联不作推断':
   `已关联调用 ${events.length}/${snapshot.events.length} · 局部候选 ${trials.length}/${snapshot.trials.length} · 未记录关联的项不列入筛选`;
  $('#wb-events').innerHTML=`<h3>受管调用</h3><pre>${escape(JSON.stringify(events,null,2))}</pre><h3>工作流历史</h3><pre>${escape(JSON.stringify(history,null,2))}</pre><h3>局部候选</h3><pre>${escape(JSON.stringify(trials,null,2))}</pre><h3>采用记录</h3><pre>${escape(JSON.stringify(adoptions,null,2))}</pre>`;
 }
 function identity(){return Object.fromEntries(['project_id','revision','state_sha256','scene_sha256','pptx_sha256','run'].map(k=>[k,snapshot[k]]));}
 async function send(payload){
  sending=true;const button=$('#wb-form button[type=submit]');if(button)button.disabled=true;
  payload.request_id=await persistentRequestId(payload);
  sessionStorage.setItem('wb-request:'+project,payload.request_id);
  try{request=await api('workbench.edit',payload);await showRequest();}
  catch(e){$('#wb-request').textContent=e.message+' · 未知结果只查询原请求，不自动重试';}
  finally{sending=false;if(button)button.disabled=false;}
 }
 async function showRequest(){
  const target=$('#wb-request');if(!request){target.textContent='';return;}
  const rendering=request;
  target.innerHTML=`<h3>执行 ${escape(request.status)}</h3><pre>${escape(JSON.stringify(request.checks||request.result||{},null,2))}</pre><div class="wb-trial-images"></div>${request.status==='ready'?'<label>观察记录<textarea id="wb-observation"></textarea></label><label>观察者<select id="wb-observer"><option value="browser-user">浏览器用户</option><option value="test-agent">测试Agent</option></select></label><label><input type="checkbox" id="wb-confirm">已实际检查全部对照与范围保护</label><button id="wb-adopt" disabled>明确采用</button><button id="wb-keep" disabled>保留基准</button>':''}`;
  for(const info of rendering.images||[]){const url=await image(info);if(request!==rendering||epoch!==generation||!target.isConnected)return;const img=document.createElement('img');img.src=url;img.alt=info.name;target.querySelector('.wb-trial-images').append(img);}
  if($('#wb-keep'))$('#wb-keep').onclick=()=>{sessionStorage.removeItem('wb-request:'+project);request=null;target.textContent='已保留基准，候选证据保留';};
  if($('#wb-adopt'))$('#wb-adopt').onclick=async()=>{
   if(sending||!$('#wb-confirm').checked||!$('#wb-observation').value.trim())return;
   const candidate=request.request_id;
   await send({project,request_id:crypto.randomUUID().replaceAll('-',''),action:'adopt',identity:identity(),candidate_request:candidate,
    observation:{note:$('#wb-observation').value,reviewer:$('#wb-observer').value,confirmed:true}});
   draft=null;staged={};stagedIdentity=null;
  };
  if($('#wb-adopt'))$('#wb-adopt').disabled=false;
  if($('#wb-keep'))$('#wb-keep').disabled=false;
 }
 async function paint(){
  if(epoch!==generation)return;
  const s=snapshot;
  pageIndex=Math.max(0,Math.min(pageIndex,s.pages.length-1));
  const page=s.pages[pageIndex];
  $('#wb-run').innerHTML='<option value="">最新版本</option>'+s.runs.map(r=>`<option value="${escape(r)}" ${r===run?'selected':''}>${escape(r)}</option>`).join('');
  $('#wb-page').innerHTML=s.pages.map((p,i)=>`<option value="${i}" ${i===pageIndex?'selected':''}>第 ${i+1} 页</option>`).join('');
  $('#wb-status').title=`${s.project_id} · ${s.run||'暂无版本'} · revision ${s.revision} · ${s.task?.kind||'无活动任务'}`;
  $('#wb-status').textContent=`${statusLabels[s.status]||s.status} · ${s.readonly?'只读':'受控编辑'}${s.budget?` · 候选 ${s.budget.candidates}/${s.budget.max_candidates} · 导出预留 ${s.budget.reserved_exports}/${s.budget.max_exports}`:''}${s.historical?' · 历史版本':''}`;
  const planningLabels={unplanned:'未规划',invalid:'规划失效',awaiting_replanning:'等待重新规划',recovery_blocked:'恢复受阻',valid:'区域规划有效'};
  $('#wb-status').append(document.createTextNode(' · '+(planningLabels[page?.planning_state]||'规划状态待核对')));
  if(s.events[0])$('#wb-status').append(document.createTextNode(` | 最近操作 ${s.events[0].action} · ${s.events[0].status}`));
  const measured=s.checks.edit_scope?.data,review=s.checks[s.run]?.data;
  if(measured?.run_id===s.run&&measured.input_hashes?.candidate===s.pptx_sha256){
   $('#wb-status').insertAdjacentHTML('beforeend',`<div class="wb-review-summary">历史检查 · 原图 ${escape(review?.four_conclusions?.reference_visual)} · 编辑范围外 ${escape(measured.edit_scope?.outside_changed_pixels)} 像素 · 设计范围外 ${escape(measured.design_scope?.outside_changed_pixels)} 像素 · ${escape(review?.separate_design_scope)}<br>${escape(s.checks.edit_scope.source)}</div>`);
  }
  if(!page){$('#wb-quality-panel').textContent='';$('.wb-canvas').innerHTML='<div class="wb-canvas-empty">当前项目尚无页面</div>';return;}
  $('#wb-quality-panel').innerHTML=qualityMarkup(page);
  $('.wb-tree').innerHTML=`<h2>区域与对象</h2>${page.regions.map(r=>`<details open><summary>${escape(r.id)} · 语义区域</summary>${page.objects.filter(o=>o.id.startsWith(page.id+'.'+r.id+'.')).map(o=>`<button data-object="${escape(o.id)}" title="${escape(o.id)}">${escape(o.id.split('.').pop())}<small>${escape(o.scene.kind)}</small></button>`).join('')}</details>`).join('')}<details><summary>全部对象 (${page.objects.length})</summary>${page.objects.map(o=>`<button data-object="${escape(o.id)}">${escape(o.id)}</button>`).join('')}</details>`;
  inspect();
  timeline();
  await canvas();
 }
 async function canvas(){
  if(!snapshot?.pages[pageIndex])return;
  const rendering=++canvasSerial,projectId=project;
  const page=snapshot.pages[pageIndex],serial=cursor, pageId=page.id;
  const isCurrent=()=>epoch===generation&&rendering===canvasSerial&&projectId===project&&serial===cursor&&pageId===snapshot?.pages[pageIndex]?.id;
  blobs.forEach(URL.revokeObjectURL);blobs=[];
  const left=pair==='reference'?page.images.reference:pair==='edit'?page.images.edit_baseline:pair==='design'?page.images.design_baseline:page.images.candidate;
  const right=['reference','design'].includes(pair)?page.images.candidate:page.images[pair];
  $('.wb-identities').textContent=[left,right].map(i=>`${i?.name||'未记录'} · ${i?.size?.join('×')||'未渲染'} · ${i?.sha256||''} · 图像保存 ${i?.modified_ns?new Date(i.modified_ns/1e6).toLocaleString():'未记录'}`).join('\n');
  if(mode==='difference'){
   const difference=pair==='reference'?page.images.reference_difference:null;
   const url=await image(difference);
   if(!isCurrent()){if(url)URL.revokeObjectURL(url);return;}
   $('.wb-canvas').innerHTML=`${url?`<img style="width:100%" src="${url}" alt="已保存的参考绝对差异图">`:'<p>本组未登记差异图片</p>'}<pre>${escape(JSON.stringify(snapshot.checks,null,2))}</pre>`;
   return;
  }
  const urls=await Promise.all([image(left),image(right)]);
  if(!isCurrent()){urls.filter(Boolean).forEach(URL.revokeObjectURL);return;}
  const boxes=page.objects.filter(o=>o.scene.bbox).map(o=>{
   const [x,y,w,h]=o.scene.bbox,c=snapshot.canvas;
   return `<button class="wb-box" data-object="${escape(o.id)}" aria-label="${escape(o.id)}" title="${escape(o.id)}" style="left:${x/c.width*100}%;top:${y/c.height*100}%;width:${w/c.width*100}%;height:${h/c.height*100}%"></button>`;
  }).join('');
  $('.wb-canvas').innerHTML=`<div class="wb-images ${mode}" style="width:${zoom}%">${urls.map((u,i)=>`<figure><figcaption>${i?'候选 / 检查副本':'参考 / 基准'}</figcaption><div class="wb-image">${u?`<img src="${u}" alt="${i?'候选':'参考'}">${i&&$('#wb-boxes').checked?boxes:''}`:'<div class="wb-image-empty"><strong>暂无预览</strong><span>未渲染或附件缺失</span></div>'}</div></figure>`).join('')}</div>`;
  inspect();
 }
 main.onclick=e=>{
  if(epoch!==generation)return;
  const choice=e.target.closest('[data-project]');
  if(choice&&choice.dataset.project!==project){project=choice.dataset.project;resetProject();saveSelection();paintProjects();poll(true);return;}
  const obj=e.target.closest('[data-object]');if(obj){selected=obj.dataset.object;inspect();}
 };
 $('#wb-project-search').oninput=e=>{search=e.target.value.trim();paintProjects();};
 refreshCurrent=()=>poll(true);
 $('#wb-refresh').onclick=refreshCurrent;
 $('#wb-run').onchange=e=>{controller?.abort();clearTimeout(timer);run=e.target.value;cursor='';selected=null;poll();};
 $('#wb-page').onchange=e=>{if(!snapshot)return;pageIndex=Number(e.target.value);selected=null;draft=null;staged={};stagedIdentity=null;paint();};
 $('#wb-pair').onchange=e=>{pair=e.target.value;canvas();};
 $('#wb-mode').onchange=e=>{mode=e.target.value;canvas();};
 $('#wb-zoom').oninput=e=>{zoom=Number(e.target.value);$('#wb-zoom-value').textContent=zoom+'%';const v=$('.wb-images');if(v)v.style.width=zoom+'%';};
 $('#wb-boxes').onchange=canvas;
 $('#wb-event-filter').onchange=e=>{eventFilter=e.target.value;timeline();};
 $('#wb-inspector-toggle').onchange=e=>$('.wb-layout').classList.toggle('hide-inspector',!e.target.checked);
 await poll(true);
}
