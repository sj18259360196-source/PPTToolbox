import {renderProjectAssistance} from './pptagent-visibility.js';
import {createImageViewer} from './project-image-viewer.js';
import {mountProjectFiles} from './project-file-browser.js';
import {mountProjectReference} from './project-reference.js';
import {mountProjectFlow} from './project-flow.js';
import {api} from './api.js';
import {projectIndex} from './project-index.js';
import {mountFolderActions} from './project-folders.js';
import {projectFamily} from './projects-model.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stages=[['intake','接单与确认'],['plan','确定方案'],['production','制作 PPT'],['revision','整理与修订'],['delivery','交付']];
const eventLabels={begin:'开始',transition:'阶段切换',finish:'交付收尾',replan:'调整方案',blocked:'等待处理',pause:'暂停',resume:'恢复'};
const callLabels={running:'执行中',started:'已受理',completed:'已完成',tool_failed:'失败',failed:'失败',outcome_unknown:'结果待确认',action_required:'等待处理',blocked:'等待处理',permission_denied:'等待授权',invalid_arguments:'参数无效',invalid_submission:'提交无效',invalid_operation:'操作无效',missing_file:'文件缺失',office_busy:'Office 被占用',writer_busy:'写入被占用',no_results:'未找到素材'};
let epoch=0,timer,refreshNow,images=[],dispose,flowView,referenceView;
export function stopWorkbench(){epoch++;clearTimeout(timer);refreshNow=null;referenceView?.dispose();referenceView=null;flowView?.dispose();flowView=null;dispose?.();dispose=null;images.forEach(URL.revokeObjectURL);images=[];}
export function refreshWorkbench(){refreshNow?.();}
export async function mountWorkbench(main){
 stopWorkbench();const generation=epoch;
 let key=new URLSearchParams(location.hash.split('?')[1]||'').get('project'),sequence=-1,current,selectedStage=null,deckPath='',page=0,busy=false,previewSerial=0,previewSignature='',previewRetry=0,callFilter=null,fetchError='',previewError='';
 const rows=(await projectIndex()).rows;if(generation!==epoch)return;
 if(!key)key=rows.find(r=>!r.error&&!r.archived)?.id;
 if(!key){main.innerHTML='<div class="panel panel-body"><h1>项目工作链</h1><p>先创建项目文件夹，或让 Agent 开始制作。</p><a href="#/projects">查看项目</a></div>';return;}
 const row=rows.find(r=>r.id===key),family=projectFamily(rows,key);
 const ancestors=[];let parent=row;const seen=new Set();while(parent&&!seen.has(parent.id)){seen.add(parent.id);ancestors.unshift(parent);parent=rows.find(r=>r.id===parent.parent_id);}
 main.innerHTML=`<section class="project-chain"><header class="chain-head"><div><nav class="chain-breadcrumb" aria-label="项目路径"><a href="#/projects">所有项目</a>${ancestors.map(r=>`<span>/</span><a href="#/workbench?project=${encodeURIComponent(r.id)}" ${r.id===key?'aria-current="page"':''}>${esc(r.label)}</a>`).join('')}</nav><h1>${esc(row?.label||'项目')}</h1></div><button data-open-root>打开文件夹</button></header><p class="small muted" id="chain-sync" role="status">正在读取项目记录</p><section id="chain-alerts" class="chain-alerts" aria-label="项目异常" aria-live="polite"></section><div class="chain-layout">${family.length>1?`<details class="chain-tree"><summary>关联项目 · ${family.length}</summary><div>${tree(family,null,key)}</div></details>`:''}<section class="chain-reference-panel panel panel-body"><h2>参考图</h2><div id="chain-reference"></div></section><section class="chain-overview panel panel-body" id="chain-overview"></section><section class="chain-preview-panel panel panel-body"><h2>当前 PPT</h2><div id="chain-preview"></div></section><section class="chain-assistance panel panel-body" id="chain-assistance" aria-label="PPTAgent 辅助状态"></section><nav class="chain-tabs" role="tablist" aria-label="项目详情">${[['flow','运行路径'],['files','项目文件'],['records','制作记录'],['helper','助手摘要']].map(([id,label],i)=>`<button id="chain-tab-${id}" role="tab" aria-controls="chain-pane-${id}" aria-selected="${!i}" tabindex="${i?-1:0}" data-chain-tab="${id}">${label}</button>`).join('')}</nav><section id="chain-pane-flow" role="tabpanel" aria-labelledby="chain-tab-flow" class="chain-flow-panel panel panel-body"><div class="chain-section-head"><h2>运行路径</h2><span class="small muted">自动排布与连线</span></div><div id="project-flow"></div></section><div id="chain-pane-records" role="tabpanel" aria-labelledby="chain-tab-records" class="chain-body" hidden><details class="panel panel-body chain-stage-details"><summary>大阶段记录</summary><div class="stage-list" id="stage-list"></div><div id="stage-detail"></div></details><details class="panel panel-body chain-auxiliary"><summary>实际工具调用</summary><div id="chain-calls"></div></details><details class="panel panel-body chain-auxiliary"><summary>本次可用经验</summary><div id="chain-experiences"></div></details><details class="panel panel-body chain-auxiliary"><summary>路径调整与打卡记录</summary><div id="chain-checkpoints"></div></details></div><section id="chain-pane-helper" role="tabpanel" aria-labelledby="chain-tab-helper" class="chain-side panel panel-body" hidden><h2>助手摘要</h2><div id="chain-helper"></div></section><section id="chain-pane-files" role="tabpanel" aria-labelledby="chain-tab-files" class="chain-file-browser panel panel-body" hidden><div id="chain-files"></div></section></div></section>`;
 const $=id=>main.querySelector('#'+id);
 const viewer=createImageViewer(main);let filesMounted=false;
 function selectTab(id){
  main.querySelectorAll('[data-chain-tab]').forEach(b=>{const selected=b.dataset.chainTab===id;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;$('chain-pane-'+b.dataset.chainTab).hidden=!selected;});
  if(id==='files'&&!filesMounted){filesMounted=true;mountProjectFiles($('chain-files'),key,false,{initialGroup:'delivery'}).catch(e=>{filesMounted=false;$('chain-files').textContent=e.message;});}
 }
 main.querySelector('.chain-tabs').onclick=e=>{const id=e.target.closest('[data-chain-tab]')?.dataset.chainTab;if(id)selectTab(id);};
 main.querySelector('.chain-tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...main.querySelectorAll('[data-chain-tab]')],index=buttons.indexOf(document.activeElement);if(index<0)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;selectTab(buttons[next].dataset.chainTab);buttons[next].focus();};
 referenceView=mountProjectReference($('chain-reference'),key);referenceView.refresh();
 flowView=mountProjectFlow($('project-flow'),{onAction:flowAction});
 const notesButton=document.createElement('button');notesButton.textContent='项目说明';notesButton.dataset.notes='';main.querySelector('.chain-head').append(notesButton);
 mountFolderActions(main,async()=>{},()=>rows,{parent:key});
 function tree(rows,parent,selected,depth=0,seen=new Set()){
  if(depth>12)return '';
  return rows.filter(r=>(r.parent_id||null)===parent&&!seen.has(r.id)).map(r=>{
   seen.add(r.id);const link=`<a href="#/workbench?project=${encodeURIComponent(r.id)}" class="${r.id===selected?'selected':''}" ${r.id===selected?'aria-current="page"':''}>${esc(r.label)}</a>`;
   const children=tree(rows,r.id,selected,depth+1,seen);
   return children?`<details class="chain-folder" open><summary>${link}</summary><div>${children}</div></details>`:link;
  }).join('');
 }
 function paint(s){
  current=s;flowView.update(s);alerts();const phase=s.phase||{},index=stages.findIndex(([id])=>id===phase.stage),finished=phase.status==='finished'&&phase.artifact_state==='present';
  const active=(s.activity?.calls||[]).filter(c=>c.status==='running').at(-1);
  const unresolved=(s.activity?.issues||[]).filter(i=>i.state==='open');
  const title=unresolved.some(i=>i.severity==='error')?'项目有异常需要核对':unresolved.length?'项目有事项等待处理':active?`${active.tool} 正在执行`:phase.status==='blocked'?'等待处理':phase.status==='paused'?'制作已暂停':finished?'交付收尾已登记':index>=0?`${stages[index][1]} · 已登记开始`:s.workflow_status==='delivered'?'已有交付记录 · 阶段未登记':'等待大阶段打卡';
  const count=finished?5:Math.max(index,0);
  $('chain-overview').innerHTML=`<div class="chain-current"><span class="chain-dot ${active?'running':''}"></span><strong>${esc(title)}</strong></div><p class="small muted">${unresolved.length?'请先核对上方异常，已有产物与记录继续保留':active?'软件已记录工具启动，等待返回结果':phase.result_summary?esc(phase.result_summary):'软件自动收集已能观察到的调用与文件变化'}</p><progress max="5" value="${count}" aria-label="大阶段进度"></progress><div class="chain-progress-label">${count} / 5 个阶段已登记完成${s.checkpoint_required?'':' · 既有项目，可从首次打卡开始记录'}</div><p class="chain-next">下一步　${esc(unresolved[0]?.next_action||phase.next_action||'等待制作 Agent 登记')}</p>${phase.blocker?`<p class="chain-warning">${esc(phase.blocker)}</p>`:''}${phase.status==='finished'&&!finished?'<p class="chain-warning">Agent 已登记收尾，关联产物仍待确认。</p>':''}`;
  $('stage-list').innerHTML=stages.map(([id,label],i)=>`<button data-stage="${id}" class="stage-node ${i<index||finished?'done':i===index?'current':'planned'}"><span>${i+1}</span><strong>${label}</strong><small>${i<index||finished?'已打卡':i===index?'当前阶段':'待执行'}</small></button>`).join('');
  $('stage-list').onclick=e=>{const id=e.target.closest('[data-stage]')?.dataset.stage;if(id){selectedStage=id;detail();}};detail();
  const calls=s.activity?.calls||[];
  const connection=s.activity?.connection;
  $('chain-overview').insertAdjacentHTML('beforeend',`<details class="chain-connection"><summary>${connection?.connected_count?'Agent 已连接':'Agent 未连接'}</summary><p>连接情况不代表本项目正在执行，其他软件中的活动暂不可见。</p></details>`);
  renderCalls();
  const used=new Set((s.checkpoints||[]).flatMap(c=>c.used_experiences||[]));
  $('chain-experiences').innerHTML=(s.recommendations||[]).map(r=>`<details class="experience-card"><summary><b>${esc(r.title)}</b><span>${used.has(r.id)?'Agent 已报告采用':'供本阶段参考'}</span></summary><p>${esc(r.trigger)}</p><ol>${r.actions.map(a=>`<li>${esc(a)}</li>`).join('')}</ol><p class="small muted">${esc(r.constraints.join('；'))}</p><p class="small muted">${esc(r.id)} · 来源 ${esc(r.sources.map(x=>x.source_id).join('、'))} · 历史方法，当前效果待验证</p></details>`).join('')||'<p class="muted">当前没有足够相关的经验，软件不会凑满推荐数量。</p>';
  const checks=s.checkpoints||[];
  $('chain-checkpoints').innerHTML=checks.slice(-30).reverse().map(c=>`<details class="checkpoint-record ${c.event==='replan'?'branch':''}"><summary>${c.event==='replan'?'↳ ':''}${esc(eventLabels[c.event])} · ${esc(Object.fromEntries(stages)[c.stage])}<small>${esc(new Date(c.received_at).toLocaleString())}</small></summary><p>${esc(c.result_summary)}</p><p>下一步　${esc(c.next_action||'未登记')}</p>${c.artifact_refs?.length?`<p>相关文件　${esc(c.artifact_refs.join('、'))}</p>`:''}${c.used_experiences?.length?`<p>实际采用　${esc(c.used_experiences.join('、'))}</p>`:''}<p class="small muted">记录来自制作 Agent，工具执行与产物状态单独核对。</p></details>`).join('')||'<p class="muted">尚无阶段打卡。此前的调用记录继续保留。</p>';
  const helper=s.summary||{};
  $('chain-helper').innerHTML=`<p>${esc(helper.status==='ready'?'后台整理已更新':helper.status==='unavailable'?helper.message:'本地采集正常，可在 Agent 接入中配置 API')}</p>${helper.summary?`<p class="helper-summary">${esc(helper.summary)}</p><p class="small muted">${helper.status==='unavailable'?'上次整理，尚未同步本次变化':'辅助归纳'} · ${esc((helper.evidence_ids||[]).join('、'))}</p>`:''}${helper.next_hint?`<p class="small muted">预计后续　${esc(helper.next_hint)}</p>`:''}${s.management_note?`<p class="small muted">PPTAgent 管理备注</p><p class="helper-summary">${esc(s.management_note.text)}</p>`:''}<a href="#/pptagent?project=${encodeURIComponent(key)}">打开管理助手</a>`;
  // File inventory is loaded on demand, with explicit delivery/history groups.

 }
 function alerts(){
  const s=current||{},issues=(s.activity?.issues||[]).filter(i=>i.state==='open');
  const sync=fetchError||s.observer_error||s.manifest_warning;
  const time=s.updated_at?new Date(s.updated_at).toLocaleString():'尚未成功读取';
  $('chain-alerts').innerHTML=(sync?`<div class="chain-incident error" role="alert"><strong>项目状态暂未更新</strong><p>${esc(sync)}</p><small>最近可用记录 ${esc(time)} · 当前显示保留内容，恢复后自动更新</small></div>`:'')+
   (previewError?`<div class="chain-incident warning"><strong>当前 PPT 预览待更新</strong><p>${esc(previewError)}</p></div>`:'')+
   issues.map((i,index)=>`<details class="chain-incident ${esc(i.severity)}" ${index===0?'open':''}><summary>${esc(i.title)}<span>${esc(i.tool)}</span></summary><p>${esc(i.message)}</p><p>${esc(i.next_action)}</p><div class="actions"><small>${esc(new Date(i.at).toLocaleString())} · ${esc(i.evidence_id)}</small><button data-show-call="${esc(i.id)}">查看调用</button><button data-ack-issue="${esc(i.id)}" title="仅收起提示，保留异常记录，不代表任务已成功">已核对，收起提示</button></div></details>`).join('')+
   (s.phase?.artifacts?.some(f=>!f.exists)?'<div class="chain-incident error"><strong>交付记录中的文件缺失</strong><p>请核对项目文件夹。交付完成状态暂不确认。</p><button data-flow-jump="files">查看项目文件</button></div>':'')+
   (s.activity?.file_scan_limited?'<div class="chain-incident warning">文件数量超过本次扫描范围，未列出的文件需要到项目文件夹核对。</div>':'');
  $('chain-alerts').hidden=!$('chain-alerts').innerHTML;
 }
 function renderCalls(){
  const rows=new Map((current?.activity?.calls||[]).map(c=>[c.id,c]));
  for(const issue of current?.activity?.issues||[])rows.set(issue.id,{...rows.get(issue.id),...issue});
  const calls=[...rows.values()].filter(c=>!callFilter||callFilter.includes(c.id)).reverse();
  $('chain-calls').innerHTML=(callFilter?'<button data-all-calls>显示全部调用</button>':'')+(calls.length?calls.map(c=>`<details class="chain-call ${/failed|unknown|invalid|denied/.test(c.status)?'attention':''}"><summary><strong>${esc(c.tool)}</strong><span>${esc(callLabels[c.status]||c.status)}</span></summary><p>${esc(c.message||'没有补充错误信息')}</p><p>${esc(c.next_action||'')}</p><small>${esc(c.task_id||'')} · ${esc(new Date(c.at).toLocaleString())} · ${esc(c.evidence_id)}</small>${c.state==='acknowledged'?'<p class="small muted">已由用户收起提示，原始异常记录保留。</p>':''}<p class="small muted">调用编号 ${esc(c.id)}</p></details>`).join(''):'<p class="muted">尚无可关联的调用记录。阶段登记不代表工具已经运行。</p>');
 }
 function flowAction(action,node){
  if(action==='notes'){editNotes();return;}
  if(action==='icons'||action==='graphics'){location.hash=`#/${action}?project=${encodeURIComponent(key)}`;return;}
  if(action==='calls')selectTab('records');else if(action==='files')selectTab('files');
  const target=$(action==='calls'?'chain-calls':action==='preview'?'chain-preview':'chain-files');
  if(action==='calls'){callFilter=node?.call_ids||null;renderCalls();target.closest('details').open=true;}
  target.scrollIntoView({block:'center',behavior:'smooth'});target.classList.remove('chain-highlight');void target.offsetWidth;target.classList.add('chain-highlight');
 }
 function detail(){const stage=selectedStage||current?.phase?.stage;const records=(current?.checkpoints||[]).filter(c=>c.stage===stage||c.from_stage===stage);$('stage-detail').innerHTML=records.length?`<p class="small muted">${esc(records.at(-1).result_summary)}</p>`:'';}
 async function preview(){
  const request=++previewSerial;
  const result=await api('project.simple-previews',undefined,{project:key});if(generation!==epoch||request!==previewSerial)return;
  previewError='';alerts();
  previewRetry=(result.decks||[]).some(d=>/正在保存|等待扫描/.test(d.state))?Date.now()+3000:0;
  const decks=result.decks||[];if(!decks.length){previewSignature='';deckPath='';page=0;images.forEach(URL.revokeObjectURL);images=[];$('chain-preview').innerHTML='<div class="simple-preview-empty">Agent 保存 PPT 后，软件会自动发现文件与匹配预览。</div>';return;}
  let deck=decks[0];if(deckPath!==deck.path)page=0;deckPath=deck.path;page=Math.min(page,Math.max(0,deck.slides.length-1));
  const signature=JSON.stringify([decks,deckPath,page]);if(signature===previewSignature)return;
  $('chain-preview').innerHTML=`${deck.slides.length?'<button class="chain-slide-image" aria-label="放大当前 PPT"><img alt="当前 PPT 页面" id="simple-slide"></button>':'<div class="simple-preview-empty">已有 PPT，预览待更新</div>'}<div class="chain-media-footer"><span title="${esc(deck.path)}">${esc(deck.name)}</span><div class="simple-preview-pager"><button id="chain-prev" aria-label="上一页 PPT" ${page===0?'disabled':''}>‹</button><span>${deck.slides.length?page+1:0} / ${deck.slides.length}</span><button id="chain-next" aria-label="下一页 PPT" ${page>=deck.slides.length-1?'disabled':''}>›</button></div></div><div class="chain-media-actions"><span class="small muted">${esc(deck.state)}</span><div class="actions">${deck.slides.length?'<button data-enlarge-ppt>放大预览</button>':''}<button data-open="${esc(deckPath)}">打开 PPT</button></div></div>`;
  const readSlide=async()=>{const response=await fetch('/api/project.simple-image?'+new URLSearchParams({project:key,path:deck.slides[page]}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});if(!response.ok)throw Error('预览已变化，稍后自动刷新');return response.blob();};
  $('chain-preview').querySelector('.chain-slide-image')?.addEventListener('click',()=>viewer.open('当前 PPT · '+deck.name,readSlide).catch(showPreviewError));
  $('chain-preview').querySelector('[data-enlarge-ppt]')?.addEventListener('click',()=>viewer.open('当前 PPT · '+deck.name,readSlide).catch(showPreviewError));
  $('chain-prev').onclick=()=>{page--;preview().catch(showPreviewError);};$('chain-next').onclick=()=>{page++;preview().catch(showPreviewError);};
  if(deck.slides.length){
   const response=await fetch('/api/project.simple-image?'+new URLSearchParams({project:key,path:deck.slides[page]}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
   if(!response.ok)throw Error('预览已变化，稍后自动刷新');const blob=await response.blob();if(generation!==epoch||request!==previewSerial)return;
   images.forEach(URL.revokeObjectURL);images=[URL.createObjectURL(blob)];if($('simple-slide'))$('simple-slide').src=images[0];
  }
  previewSignature=signature;
 }
 function showError(e){if(generation===epoch){fetchError=e.message;alerts();}}
 function showPreviewError(e){if(generation===epoch){previewSignature='';previewRetry=Date.now()+3000;previewError=e.message;alerts();}}
 function editNotes(){
  if(!current?.notes)return;
  const notes=current.notes,dialog=document.createElement('dialog');dialog.className='project-editor chain-notes';
  dialog.innerHTML=`<form><h2>项目说明</h2><p class="small muted">保存在项目文件夹的 ppttool.md 中，软件更新时保留这些内容。</p><textarea name="notes" aria-label="项目说明" maxlength="20000" rows="12">${esc(notes.text)}</textarea><p role="alert"></p><div class="actions"><button type="submit">保存说明</button><button type="button" data-cancel>取消</button></div></form>`;
  main.append(dialog);dialog.showModal();dialog.onclose=()=>dialog.remove();dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const button=dialog.querySelector('[type=submit]');button.disabled=true;try{await api('project.notes.save',{project:key,text:e.target.elements.notes.value,revision:notes.revision});dialog.close();await poll();}catch(error){dialog.querySelector('[role=alert]').textContent=error.message;}finally{button.disabled=false;}};
 }
 const click=async e=>{
  if(e.target.closest('.chain-file-browser'))return;
  if(e.target.closest('[data-assistant-details]')){selectTab('helper');$('chain-pane-helper').scrollIntoView({block:'start',behavior:'smooth'});return;}
  const issue=e.target.closest('[data-ack-issue]');if(issue){issue.disabled=true;try{await api('project.issue.acknowledge',{project:key,id:issue.dataset.ackIssue,sequence:current.sequence});await poll();}catch(error){showError(error);}finally{issue.disabled=false;}return;}
  const call=e.target.closest('[data-show-call]');if(call){flowAction('calls',{call_ids:[call.dataset.showCall]});return;}
  if(e.target.closest('[data-all-calls]')){callFilter=null;renderCalls();return;}
  const jump=e.target.closest('[data-flow-jump]');if(jump){flowAction(jump.dataset.flowJump);return;}
  if(e.target.closest('[data-notes]')){editNotes();return;}const file=e.target.closest('[data-open]');if(!file&&!e.target.closest('[data-open-root]'))return;try{await api('project.open',{project:key,path:file?.dataset.open,action:file?'open':'reveal'});}catch(error){showError(error);}};
 main.addEventListener('click',click);dispose=()=>{viewer.dispose();main.removeEventListener('click',click);main.querySelectorAll('.chain-notes').forEach(d=>d.remove());};
 async function poll(){
  if(generation!==epoch||busy)return;busy=true;clearTimeout(timer);
  try{const next=await api('project.activity',undefined,{project:key});if(generation!==epoch)return;
   fetchError='';current=next;alerts();referenceView.refresh();const assistanceHtml=renderProjectAssistance(next,key);if($('chain-assistance').innerHTML!==assistanceHtml)$('chain-assistance').innerHTML=assistanceHtml;
   $('chain-sync').textContent=next.observer_error||next.manifest_warning||(next.syncing?'正在建立项目记录':`记录已同步 · ${new Date(next.updated_at).toLocaleString()}`);
   if(sequence!==next.sequence){sequence=next.sequence;paint(next);preview().catch(showPreviewError);}
   else if(previewRetry&&Date.now()>=previewRetry){previewRetry=0;preview().catch(showPreviewError);}
  }catch(error){showError(error);}finally{busy=false;if(generation===epoch)timer=setTimeout(poll,2000);}
 }
 refreshNow=()=>{sequence=-1;return poll();};await poll();
}
