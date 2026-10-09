const stages=[['intake','接单与确认'],['plan','确定方案'],['production','制作 PPT'],['revision','整理与修订'],['delivery','交付']];
const labels={planned:'待执行',running:'进行中',done:'已完成',observed:'调用已完成',blocked:'等待处理',paused:'已暂停',skipped:'已跳过',replaced:'已调整路径',failed:'执行失败',outcome_unknown:'结果待确认'};
const stateLabel=node=>node.status_label||labels[node.status];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const relationLabels={dependency:'依赖',sequence:'顺序',decision:'决策',merge:'汇合',revision:'返修',suggested:'建议',grouping:'归属'};
const basisLabels={recorded:'记录依据',agent:'Agent 登记',inferred:'Agent 推断',suggested:'预设建议'};
export function edgeInfo(node,parent){
 const link=(node.links||[]).find(l=>l.from===parent)||{};
 const relation=relationLabels[link.relation]?link.relation:'dependency';
 const basis=basisLabels[link.basis]?link.basis:'agent';
 return {relation,basis,label:link.label||relationLabels[relation],shortLabel:relationLabels[relation],
  evidence_ids:link.evidence_ids||[],basisLabel:basisLabels[basis]};
}
export function renderRelations(node,graph){
 const edges=graph.edges.filter(e=>e.from===node.id||e.to===node.id);
 return edges.map(e=>{
  const name=id=>graph.nodes.find(n=>n.id===id)?.title||id;
  return `<li><strong>${esc(name(e.from))} → ${esc(name(e.to))}</strong><span>${esc(e.label)} · ${esc(e.basisLabel)}</span>${e.evidence_ids?.length?`<small>依据 ${e.evidence_ids.map(esc).join('、')}</small>`:''}</li>`;
 }).join('');
}

const visualBytes=value=>Number.isFinite(value)?(value/1048576).toFixed(2)+' MiB':'未知';
export function renderVisualActivity(visual){
 if(!visual)return '<p class="small muted">图片统计尚未采集，等待项目观察器更新。</p>';
 const card=(label,value,note)=>`<div><span>${esc(label)}</span><strong>${esc(value??'未知')}</strong><small>${esc(note)}</small></div>`;
 const counts=(name,label)=>{const row=visual[name];return card(label,row?row.required+' / '+row.submitted:null,'要求查看 / 已提交观察 · 张次');};
 const diagnostics=(visual.diagnostics||[]).map(d=>`<li>${esc(d.task_id||'记录')} ${esc(d.path||'')}<br>${esc(d.message)}</li>`).join('');
 const active=visual.active;
 return `<section class="flow-visual" aria-label="图片使用统计"><div class="flow-visual-head"><strong>图片使用统计</strong><small>${visual.coverage==='available'?'已采集任务记录':visual.coverage==='partial'?'统计不完整':'统计不可用'}</small></div><div class="flow-visual-cards">${counts('overview','整页主视觉')}${counts('detail','高清局部')}${card('重复图片要求',visual.repeat_image_requirements,'跨任务同哈希重复 · 张次')}${card('审查复用',visual.retained_source_reviews==null?null:visual.retained_source_reviews+' / '+visual.retained_visual_reviews,'当前原图核对 / 视觉观察')}</div><p class="small">累计必看文件 ${visualBytes(visual.required_file_bytes)} · 最近 24 个看图任务 ${visualBytes(visual.recent_required_file_bytes)} · 最近重复领取 ${esc(visual.repeated_next_calls??'未知')} 次</p><p class="small muted">${esc(visual.measurement_note||'')}<br>宿主实际看图次数、请求上传量和供应商延迟尚不可观测。${visual.timed_calls?` 最近 ${esc(visual.timed_calls)} 次已计时工具调用合计 ${esc(visual.tool_elapsed_seconds)} 秒。`:''}</p>${active?`<p class="flow-visual-current">当前 ${esc(active.task_id)} · ${active.scope==='detail'?'高清局部':'整页主视觉'} · ${esc(active.required)} 张必看图</p>`:''}${diagnostics?`<div class="flow-visual-error" role="alert"><strong>图片或观察记录需要核对 · ${esc(visual.diagnostic_count)} 项</strong><ul>${diagnostics}</ul><p>先核对当前任务和文件，再继续制作；统计异常不会被记为审查通过。</p></div>`:''}${visual.limited?'<p class="flow-visual-warning">历史任务超过统计范围，当前数值仅覆盖部分记录。</p>':''}${(visual.notices||[]).map(n=>`<p class="flow-visual-warning">${esc(n)}</p>`).join('')}<details><summary>最近看图任务与续作方法</summary><p>当前上下文中已看过同任务同哈希图片时继续工作。图片积累后保存发现，从项目状态和当前任务在短对话中接续。遇到宿主断流，恢复后登记 blocked 或 resume 及报错；工具箱无法自动看到宿主外部连接错误。</p>${(visual.recent_tasks||[]).map(t=>`<p class="flow-visual-task">${esc(t.task_id)} · ${t.scope==='detail'?'局部':'整页'} · ${esc(t.required)} 张 · ${visualBytes(t.file_bytes)} · ${t.observation_submitted?'已有观察回执':'未提交观察'}<small>${esc(t.target?.slide_id||'')}${t.target?.region_id?' / '+esc(t.target.region_id):''}</small></p>`).join('')}</details></section>`;
}

export function projectGraph(state){
 if(state.display_graph?.nodes?.length)return state.display_graph.nodes.map(n=>({...n,after:[...(n.after||[])]}));
 const custom=state.work_graph?.nodes;
 const phase=state.phase||{},current=stages.findIndex(([id])=>id===phase.stage);
 let nodes;
 if(custom?.length)nodes=custom.map(n=>({...n,after:[...(n.after||[])]}));
 else{
  const done=new Set((state.checkpoints||[]).filter(c=>c.event==='transition').map(c=>c.from_stage));
  nodes=stages.map(([id,title],i)=>({id,title,stage:id,after:i?[stages[i-1][0]]:[],source:'stage',
   status:phase.status==='finished'&&phase.artifact_state==='present'?'done':i===current?(phase.status==='paused'?'paused':phase.status==='blocked'?'blocked':'running'):i<current&&done.has(id)?'done':'planned',
   detail:i===current?(phase.blocker||phase.result_summary||''):''}));
 }
 const calls=state.activity?.calls||[];
 for(const node of nodes){
  node.evidence=node.source==='stage'?'阶段打卡':node.source==='pptagent'?'PPTAgent 整理':'制作 Agent 登记';
  // A tool can prove it is running; completion of one call cannot finish a whole step.
  const relevant=calls.filter(c=>(!node.updated_at||!c.at||Date.parse(c.at)>=Date.parse(node.updated_at))&&(custom?.length
   ?node.tools?.includes(c.tool):node.stage===phase.stage)).at(-1);
  if(relevant&&!['done','skipped','replaced'].includes(node.status)){
   if(relevant.status==='running'){
    node.status='running';node.evidence='工具正在执行';node.observedTool=relevant.tool;
   }else if(!['completed','succeeded','passed','ok'].includes(relevant.status)){
    node.status=relevant.status==='outcome_unknown'?'outcome_unknown':['permission_denied','action_required','blocked','office_busy','writer_busy','no_results'].includes(relevant.status)?'blocked':'failed';
    node.evidence=labels[node.status];
    node.detail=[node.evidence+' · '+relevant.tool,relevant.message,node.detail].filter(Boolean).join('\n');
   }
  }
  if(!labels[node.status])node.status='planned';
 }
 return nodes;
}

export function layoutGraph(nodes,available=600){
 if(nodes.length>64)throw Error('工作图步骤超过显示上限');
 const byId=new Map(nodes.map(n=>[n.id,{...n,after:[...(n.after||[])]}]));
 if(byId.size!==nodes.length)throw Error('工作图步骤编号重复');
 for(const n of byId.values())if(n.after.some(id=>!byId.has(id)||id===n.id))throw Error('工作图连接需要核对');
 const ranked=new Map(),pending=[...byId.values()];
 while(pending.length){
  const ready=pending.filter(n=>n.after.every(id=>ranked.has(id)));
  if(!ready.length)throw Error('工作图存在循环，返工应另建步骤');
  for(const n of ready){ranked.set(n.id,n.after.length?1+Math.max(...n.after.map(id=>ranked.get(id))):0);pending.splice(pending.indexOf(n),1);}
 }
 const ranks=[];
 for(const n of byId.values()){const rank=ranked.get(n.id);(ranks[rank]??=[]).push(n);}
 if(!nodes.length)return {nodes:[],edges:[],routes:[],width:Math.max(240,available),height:0,bands:0,columns:0};
 const padding=24,gapX=48,gapY=24,nodeHeight=80,bandGap=52;
 const columns=[];
 // Bound both dimensions: long sequences wrap and wide forks use groups of three.
 for(const rank of ranks)for(let i=0;i<rank.length;i+=3)columns.push(rank.slice(i,i+3));
 const capacity=Math.max(1,Math.min(6,columns.length,Math.floor((available-padding*2+gapX)/(152+gapX))));
 const nodeWidth=Math.min(186,Math.max(152,(available-padding*2-gapX*(capacity-1))/capacity));
 const width=padding*2+capacity*nodeWidth+(capacity-1)*gapX;
 let top=padding,step=0;
 for(let start=0;start<columns.length;start+=capacity){
  const band=columns.slice(start,start+capacity),lanes=Math.max(...band.map(c=>c.length));
  band.forEach((column,col)=>{
   const weight=n=>n.after.length?n.after.reduce((s,id)=>s+(byId.get(id).lane||0),0)/n.after.length:0;
   column.sort((a,b)=>weight(a)-weight(b));
   const positions=[];
   column.forEach((n,i)=>positions.push(Math.max(Math.min(lanes-1,weight(n)),i?positions[i-1]+1:0)));
   positions[positions.length-1]=Math.min(lanes-1,positions.at(-1));
   for(let i=positions.length-2;i>=0;i--)positions[i]=Math.min(positions[i],positions[i+1]-1);
   column.forEach((n,i)=>{
    const lane=positions[i];
    Object.assign(n,{x:padding+col*(nodeWidth+gapX),y:top+lane*(nodeHeight+gapY),width:nodeWidth,height:nodeHeight,
     rank:ranked.get(n.id),band:Math.floor(start/capacity),column:col,lane,step:++step});
   });
  });
  top+=lanes*nodeHeight+(lanes-1)*gapY+bandGap;
 }
 const height=top-bandGap+padding;
 const children=new Map([...byId.keys()].map(id=>[id,[]]));
 for(const n of byId.values())for(const id of n.after)children.get(id).push(n.id);
 const routes=new Map([['main',{id:'main',label:'主路径',tone:0}]]),forkRoutes=new Map();
 const toneFor=id=>1+[...id].reduce((value,c)=>(value*31+c.charCodeAt(0))>>>0,0)%5;
 for(const [id,childIds] of children)if(childIds.length>1){
  const used=new Set();
  for(const childId of childIds){
   let tone=toneFor(childId);while(used.size<5&&used.has(tone))tone=tone%5+1;
   used.add(tone);forkRoutes.set(id+'>'+childId,{id:childId,label:byId.get(childId).title||childId,tone});
  }
 }
 for(const n of [...byId.values()].sort((a,b)=>a.rank-b.rank)){
  const parentRoutes=n.after.map(id=>byId.get(id).route);
  n.route=n.after.length===1?(forkRoutes.get(n.after[0]+'>'+n.id)||parentRoutes[0]):
   parentRoutes.length&&parentRoutes.every(r=>r.id===parentRoutes[0].id)?parentRoutes[0]:routes.get('main');
  routes.set(n.route.id,n.route);
 }
 const router=orthogonalRouter([...byId.values()],width,height,padding,gapX,gapY,capacity);
 const edges=[];
 for(const n of byId.values())for(const id of n.after){
  const parent=byId.get(id),route=forkRoutes.get(id+'>'+n.id)||parent.route,points=router(parent,n,route.tone);
  edges.push({from:id,to:n.id,points,path:roundedPath(points),tone:route.tone,...edgeInfo(n,id),
   muted:[parent.status,n.status].some(status=>['skipped','replaced'].includes(status))});
 }
 return {nodes:[...byId.values()],edges,routes:[...routes.values()],width,height,bands:Math.ceil(columns.length/capacity),columns:capacity};
}

export function edgeBadges(graph){
 const occupied=[];
 return graph.edges.flatMap(e=>{
  const segments=e.points.slice(1).map((b,i)=>({a:e.points[i],b})).sort((a,b)=>
   (Math.abs(b.a.x-b.b.x)+Math.abs(b.a.y-b.b.y))-(Math.abs(a.a.x-a.b.x)+Math.abs(a.a.y-a.b.y)));
  for(const {a,b} of segments){
   if(Math.abs(a.x-b.x)+Math.abs(a.y-b.y)<32)continue;
   const box={x:(a.x+b.x)/2-14,y:(a.y+b.y)/2-8,width:28,height:16};
   const overlap=n=>box.x<n.x+n.width+3&&box.x+box.width>n.x-3&&box.y<n.y+n.height+3&&box.y+box.height>n.y-3;
   if([...graph.nodes,...occupied].some(overlap))continue;
   occupied.push(box);return [{...box,edge:e}];
  }
  return [];
 });
}

function roundedPath(points){
 let path=`M ${points[0].x} ${points[0].y}`;
 for(let i=1;i<points.length-1;i++){
  const a=points[i-1],b=points[i],c=points[i+1],ab=Math.hypot(b.x-a.x,b.y-a.y),bc=Math.hypot(c.x-b.x,c.y-b.y),r=Math.min(5,ab/2,bc/2);
  path+=` L ${b.x-(b.x-a.x)*r/ab} ${b.y-(b.y-a.y)*r/ab} Q ${b.x} ${b.y} ${b.x+(c.x-b.x)*r/bc} ${b.y+(c.y-b.y)*r/bc}`;
 }
 return path+` L ${points.at(-1).x} ${points.at(-1).y}`;
}

// Route in the gutters between cards. No connector may cross a card, including
// a shortcut over several columns or a return to the beginning of the next row.
function orthogonalRouter(nodes,width,height,padding,gapX,gapY,columns){
 const nodeWidth=nodes[0].width,xs=Array.from({length:columns+1},(_,i)=>padding-gapX/2+i*(nodeWidth+gapX));
 const ys=[...new Set([padding/2,height-padding/2,...nodes.flatMap(n=>[n.y-gapY/2,n.y+n.height/2,n.y+n.height+gapY/2])])].sort((a,b)=>a-b);
 const cells=xs.flatMap((x,xi)=>ys.map((y,yi)=>({x,y,xi,yi}))),links=cells.map(()=>[]),used=new Map();
 const intersects=(a,b,n)=>a.y===b.y?a.y>n.y-6&&a.y<n.y+n.height+6&&Math.max(a.x,b.x)>n.x-6&&Math.min(a.x,b.x)<n.x+n.width+6:
  a.x>n.x-6&&a.x<n.x+n.width+6&&Math.max(a.y,b.y)>n.y-6&&Math.min(a.y,b.y)<n.y+n.height+6;
 for(let i=0;i<cells.length;i++){
  const a=cells[i];
  for(const j of [a.xi<xs.length-1?i+ys.length:-1,a.yi<ys.length-1?i+1:-1]){
   if(j<0)continue;const b=cells[j];if(nodes.some(n=>intersects(a,b,n)))continue;
   const key=i+':'+j,axis=a.y===b.y?0:1,length=Math.abs(a.x-b.x)+Math.abs(a.y-b.y);
   links[i].push({to:j,axis,length,key});links[j].push({to:i,axis,length,key});
  }
 }
 return (from,to,tone)=>{
  const start=(from.column+1)*ys.length+ys.indexOf(from.y+from.height/2),end=to.column*ys.length+ys.indexOf(to.y+to.height/2);
  const scores=new Map([[start*2,0]]),previous=new Map(),heap=[];
  const push=item=>{let i=heap.length;heap.push(item);while(i){const p=(i-1)>>1;if(heap[p].priority<=item.priority)break;heap[i]=heap[p];i=p;}heap[i]=item;};
  const pop=()=>{const first=heap[0],last=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let c=i*2+1;if(c+1<heap.length&&heap[c+1].priority<heap[c].priority)c++;if(last.priority<=heap[c].priority)break;heap[i]=heap[c];i=c;}heap[i]=last;}return first;};
  const estimate=id=>Math.abs(cells[id].x-cells[end].x)+Math.abs(cells[id].y-cells[end].y);
  push({state:start*2,cost:0,priority:estimate(start)});let finish;
  while(heap.length){
   const current=pop();if(current.cost!==scores.get(current.state))continue;
   const id=Math.floor(current.state/2),axis=current.state%2;if(id===end){finish=current.state;break;}
   for(const link of links[id]){
    const next=link.to*2+link.axis,occupied=used.get(link.key),penalty=occupied&&!occupied.has(tone)?9:0;
    const cost=current.cost+link.length+(axis===link.axis?0:14)+penalty;
    if(cost>=(scores.get(next)??Infinity))continue;
    scores.set(next,cost);previous.set(next,{state:current.state,key:link.key});push({state:next,cost,priority:cost+estimate(link.to)});
   }
  }
  if(finish===undefined)throw Error('工作图连线无法排布，请核对步骤关系');
  const route=[];
  for(let at=finish;at!==undefined;){
   route.push(cells[Math.floor(at/2)]);const prev=previous.get(at);
   if(prev){if(!used.has(prev.key))used.set(prev.key,new Set());used.get(prev.key).add(tone);}at=prev?.state;
  }
  const points=[{x:from.x+from.width,y:from.y+from.height/2},...route.reverse(),{x:to.x-6,y:to.y+to.height/2}],simple=[];
  for(const point of points){
   const b=simple.at(-1);if(b&&b.x===point.x&&b.y===point.y)continue;
   const a=simple.at(-2);if(a&&((a.x===b.x&&b.x===point.x)||(a.y===b.y&&b.y===point.y)))simple.pop();
   simple.push({x:point.x,y:point.y});
  }
  return simple;
 };
}

export function mountProjectFlow(root,options={}){
 let state={},selected=null,zoom=1,fit=true,last='',disposed=false,whole=false,lastWidth=0,resizeFrame;
 const marker='flow-arrow-'+Math.random().toString(36).slice(2);
 root.innerHTML=`<div class="flow-toolbar"><p class="small muted">从左到右，满行后接下一行</p><div class="actions"><button data-flow-zoom="out" aria-label="缩小工作图">−</button><button data-flow-zoom="fit">适应宽度</button><button data-flow-zoom="all">全图</button><button data-flow-zoom="in" aria-label="放大工作图">＋</button></div></div><div class="flow-legend" aria-label="路径颜色"></div><div class="flow-viewport" tabindex="0" aria-label="项目运行流程图"><div class="flow-space"><div class="flow-canvas"></div></div></div><div class="flow-detail" role="status"></div>`;
 const viewport=root.querySelector('.flow-viewport'),space=root.querySelector('.flow-space'),canvas=root.querySelector('.flow-canvas'),detail=root.querySelector('.flow-detail');
 const visualPanel=document.createElement('div');visualPanel.className='flow-visual-container';root.prepend(visualPanel);
 const legend=root.querySelector('.flow-legend');
 let graph;
 function describe(){
  const node=graph?.nodes.find(n=>n.id===selected);
  const names=ids=>ids.map(id=>graph.nodes.find(n=>n.id===id)?.title||id).map(esc).join('、');
  const next=node?graph.edges.filter(e=>e.from===node.id).map(e=>e.to):[];
  detail.innerHTML=node?`<strong>${esc(node.title)} · ${esc(stateLabel(node))}${node.round?' · 第 '+esc(node.round)+' 轮':''}</strong><p>${esc(node.detail||'暂无补充说明')}</p>${node.result?`<p>结果　${esc(node.result)}</p>`:''}${node.next_action?`<p>下一步　${esc(node.next_action)}</p>`:''}<p class="flow-dependencies">前置　${names(node.after)||'起始步骤'}<br>后续　${names(next)||(node.stage==='delivery'?'交付阶段末端':'后续关系尚未登记')}</p><ul class="flow-relations">${renderRelations(node,graph)}</ul><small>${esc(node.observedTool||node.evidence)}${node.updated_at?' · '+esc(new Date(node.updated_at).toLocaleString()):''}</small>`:'<p class="muted small">选择步骤可查看前后关系、决策条件、结果和下一步。实线依赖、顺序或返修的依据见详情；虚线为建议，点线为阶段归属。</p>';
  if(node){
   const actions={notes:'项目说明',files:'项目文件',calls:'查看调用',preview:'当前 PPT',icons:'素材检索',graphics:'图形构造'};
   detail.insertAdjacentHTML('beforeend',`<p class="small muted">${esc(node.evidence||'')}${node.observed_at?' · '+esc(new Date(node.observed_at).toLocaleString()):''}</p><div class="flow-actions">${(node.actions||['calls']).filter(a=>actions[a]).map(a=>`<button data-flow-action="${a}">${actions[a]}</button>`).join('')}</div>`);
  }
  canvas.querySelectorAll('[data-flow-node]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.flowNode===selected)));
  canvas.querySelector('.flow-connections')?.classList.toggle('has-selection',!!node);
  canvas.querySelectorAll('[data-flow-from]').forEach(el=>el.classList.toggle('selected',el.dataset.flowFrom===selected||el.dataset.flowTo===selected));
 }
 function resize(){
  if(disposed||!graph)return;
  const scale=whole?Math.min(1,(viewport.clientWidth-12)/graph.width,600/Math.max(1,graph.height)):fit?Math.min(1,(viewport.clientWidth-12)/graph.width):zoom;
  canvas.style.transform=`scale(${scale})`;space.style.width=graph.width*scale+'px';space.style.height=graph.height*scale+'px';
 }
 function paint(){
  if(disposed)return;
  visualPanel.innerHTML=renderVisualActivity(state.activity?.visual);
  const focusId=canvas.contains(document.activeElement)?document.activeElement?.dataset.flowNode:null;
  lastWidth=viewport.clientWidth;
  try{graph=layoutGraph(projectGraph(state),Math.max(240,lastWidth-12));}
  catch(e){canvas.innerHTML='';space.style.height='0';detail.textContent=e.message;graph=null;return;}
  canvas.style.width=graph.width+'px';canvas.style.height=graph.height+'px';
  legend.innerHTML=`<p class="flow-relationship-note">${esc(state.display_graph?.relationship_note||'实线关系见详情 · 虚线为建议 · 点线为归属')}${state.display_graph?.diagnostics?.length?' 有 '+state.display_graph.diagnostics.length+' 个末端步骤尚未登记后续关系。':''}</p>`+graph.routes.slice(0,5).map(r=>`<span class="flow-tone-${r.tone}" title="${esc(r.label)}"><i></i>${esc(r.label)}</span>`).join('')+
   (graph.routes.length>5?`<span class="muted">另有 ${graph.routes.length-5} 条分支</span>`:'')+`<small>${graph.nodes.length} 个步骤${graph.bands>1?' · '+graph.bands+' 行':''}</small>`;
  canvas.innerHTML=`<svg class="flow-connections" width="${graph.width}" height="${graph.height}" aria-hidden="true"><defs>${[0,1,2,3,4,5].map(tone=>`<marker id="${marker}-${tone}" class="flow-tone-${tone}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10"/></marker>`).join('')}</defs>${graph.edges.map(e=>`<path d="${e.path}" class="flow-edge flow-tone-${e.tone} relation-${e.relation} basis-${e.basis} ${e.muted?'muted':''}" data-flow-from="${esc(e.from)}" data-flow-to="${esc(e.to)}" marker-end="url(#${marker}-${e.tone})"><title>${esc(e.label+' · '+e.basisLabel)}</title></path>`).join('')}${edgeBadges(graph).map(({x,y,edge:e})=>`<g class="flow-edge-badge" data-flow-from="${esc(e.from)}" data-flow-to="${esc(e.to)}"><title>${esc(e.label+' · '+e.basisLabel)}</title><rect x="${x}" y="${y}" width="28" height="16" rx="3"/><text x="${x+14}" y="${y+11}" text-anchor="middle">${esc(e.shortLabel)}</text></g>`).join('')}</svg>`+
   graph.nodes.map(n=>`<button class="flow-node flow-tone-${n.route.tone} ${n.status}" style="left:${n.x}px;top:${n.y}px;width:${n.width}px;height:${n.height}px" data-flow-node="${esc(n.id)}" aria-pressed="false" title="${esc(n.title)}"><span class="flow-node-meta"><small>${String(n.step).padStart(2,'0')}</small><span class="flow-state"><i></i>${esc(stateLabel(n))}</span></span><strong>${esc(n.title)}</strong></button>`).join('');
  describe();resize();
  if(focusId)[...canvas.querySelectorAll('[data-flow-node]')].find(el=>el.dataset.flowNode===focusId)?.focus({preventScroll:true});
 }
 root.addEventListener('click',event=>{
  const destination=event.target.closest('[data-flow-action]')?.dataset.flowAction;
  if(destination){options.onAction?.(destination,graph?.nodes.find(n=>n.id===selected));return;}
  const button=event.target.closest('[data-flow-node]');if(button){selected=selected===button.dataset.flowNode?null:button.dataset.flowNode;describe();return;}
  const action=event.target.closest('[data-flow-zoom]')?.dataset.flowZoom;if(!action)return;
  if(action==='fit'){fit=true;whole=false;}else if(action==='all'){whole=true;fit=false;viewport.scrollTop=0;viewport.scrollLeft=0;}else{const currentScale=whole?Math.min(1,(viewport.clientWidth-12)/(graph?.width||1),600/(graph?.height||1)):fit?Math.min(1,(viewport.clientWidth-12)/(graph?.width||1)):zoom;zoom=Math.min(1.6,Math.max(.25,currentScale+(action==='in'?.15:-.15)));fit=false;whole=false;}
  resize();
 });
 const observer=new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{if(disposed)return;if(Math.abs(viewport.clientWidth-lastWidth)>2)paint();else resize();});});observer.observe(viewport);
 return {update(next){state=next;const signature=JSON.stringify([projectGraph(next),next.activity?.visual]);if(signature!==last){last=signature;paint();}},dispose(){disposed=true;observer.disconnect();cancelAnimationFrame(resizeFrame);}};
}
