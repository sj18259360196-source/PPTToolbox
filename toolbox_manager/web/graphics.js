import {api as requestApi,copy} from './api.js';
import {projectIndex} from './project-index.js';
let epoch=0;
export function stopGraphics(){epoch++;}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const readFile=file=>new Promise((resolve,reject)=>{
 const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);
});
export async function mountGraphics(main){
 const trackingProject=new URLSearchParams(location.hash.split('?')[1]||'').get('project');
 const api=(op,body,query)=>requestApi(op,body&&trackingProject?{...body,tracking_project:trackingProject}:body,body?query:{...query,...(trackingProject?{tracking_project:trackingProject}:{})});
 const generation=++epoch;
 const info=await api('graphics.inspect');
 if(generation!==epoch)return;
 let recipe=info.example,version='',busy=false,request=0;
 main.innerHTML=`<nav class="section-nav" aria-label="素材分类"><a href="#/icons">素材库</a><a href="#/graphics">图形构造</a></nav><section class="graphics-page">
 <div class="page-head"><h1>图形构造</h1><div class="graphics-actions">
 <button id="graphics-preview">预览</button><button id="graphics-save" class="primary">生成草稿</button></div></div>
 <section class="panel" aria-label="插画重绘调用指南"><div class="panel-body"><h2>少色分层插画重绘</h2><p>先判断语义分层和边界，再选择钢笔节点或选区转路径。可复制当前工具参数与调用步骤交给 Agent。</p><label>方法<select id="illustration-route"><option value="overview">判断与两条路线</option><option value="pen">钢笔与节点</option><option value="selection">选区转路径</option></select></label><button id="illustration-guide">读取调用指南</button><button id="illustration-copy" disabled>复制给 Agent</button><a href="#/docs?path=references/illustration-agent-guide.md">阅读完整说明</a><p id="illustration-state" role="status"></p><details><summary>当前参数与步骤</summary><pre id="illustration-content"></pre></details></div></section>
 <div class="graphics-project"><label>项目目录<input id="graphics-project" type="text"></label>
 <label>草稿版本<input id="graphics-version" type="text" spellcheck="false"></label><button id="graphics-load">载入</button></div>
 <div class="graphics-workspace"><div class="graphics-view">
 <div class="graphics-image"><img id="graphics-image" alt="图形预览"></div>
 <div id="graphics-state" role="status">待预览</div><div id="graphics-result"></div></div>
 <aside class="graphics-controls"><label>对象<select id="graphics-object"></select></label>
 <div id="graphics-properties"></div>
 <details><summary>构造配方</summary><textarea id="graphics-json" aria-label="构造配方" spellcheck="false"></textarea>
 <button id="graphics-apply">应用配方</button><button id="graphics-copy">复制配方</button></details>
 <details><summary>渐变拟合</summary><label>区域图像<input id="graphics-input" type="file" accept="image/png,image/jpeg"></label>
 <label>采样掩码<input id="graphics-mask" type="file" accept="image/png"></label>
 <label>模型<select id="graphics-model"><option value="linear">线性</option><option value="radial">径向</option></select></label>
 <label>应用到<select id="graphics-channel"><option value="fill">填充</option><option value="line">描边</option></select></label>
 <label>最多色标<input id="graphics-stops" type="number" min="2" max="5" value="3"></label>
 <button id="graphics-fit">拟合</button><div id="graphics-fit-result"></div></details></aside></div></section>`;
 const $=s=>main.querySelector(s);
 let guideText='';
 $('#illustration-guide').onclick=async()=>{
  $('#illustration-copy').disabled=true;$('#illustration-state').textContent='正在读取';
  try{const result=await api('graphics.illustration_guide',{route:$('#illustration-route').value});
   if(generation!==epoch)return;guideText=JSON.stringify(result,null,2);
   $('#illustration-content').textContent=guideText;$('#illustration-copy').disabled=false;
   $('#illustration-state').textContent='已读取当前调用步骤。补齐真实输入后由 Agent 受管执行。';
  }catch(e){if(generation===epoch)$('#illustration-state').textContent=e.message;}
 };
 $('#illustration-route').onchange=()=>{guideText='';$('#illustration-copy').disabled=true;$('#illustration-content').textContent='';$('#illustration-state').textContent='方法已变更，请重新读取';};
 $('#illustration-copy').onclick=async()=>{try{await copy(guideText);$('#illustration-state').textContent='调用指南已复制';}catch(e){$('#illustration-state').textContent=e.message;}};
 if(trackingProject){const rows=(await projectIndex()).rows;if(generation!==epoch)return;$('#graphics-project').value=rows.find(r=>r.id===trackingProject)?.path||'';}
 const state=(text,error=false)=>{if(generation===epoch){$('#graphics-state').textContent=text;$('#graphics-state').classList.toggle('error',error);}};
 const rows=()=>['paths','edges','faces','curve_groups','instances'].flatMap(kind=>(recipe[kind]||[]).map(value=>({kind,value})));
 const current=()=>rows().find(r=>r.value.id===$('#graphics-object').value);
 function sync(){
  const selected=$('#graphics-object').value;
  $('#graphics-object').innerHTML=rows().map(r=>`<option value="${esc(r.value.id)}">${esc(r.value.id)}</option>`).join('');
  if(rows().some(r=>r.value.id===selected))$('#graphics-object').value=selected;
  $('#graphics-json').value=JSON.stringify(recipe,null,2);
  properties();
 }
 function properties(){
  const row=current();if(!row)return;
  const o=row.value;
  let html='';
  if(row.kind==='curve_groups'){
   html+=`<label>模式<select data-field="mode">${[['interpolate','曲线插值'],['affine_repeat','仿射重复'],['offset','等距偏移']].map(([v,l])=>`<option value="${v}" ${o.mode===v?'selected':''}>${l}</option>`).join('')}</select></label>`;
   html+=`<label>源路径<select data-field="source">${(recipe.paths||[]).map(p=>`<option value="${esc(p.id)}" ${p.id===o.source?'selected':''}>${esc(p.id)}</option>`).join('')}</select></label>`;
   if(o.mode==='interpolate'){
    html+=`<label>终点路径<select data-field="target">${(recipe.paths||[]).map(p=>`<option value="${esc(p.id)}" ${p.id===o.target?'selected':''}>${esc(p.id)}</option>`).join('')}</select></label>`;
   }
   if(o.mode!=='offset')html+=`<label>曲线数量<input data-field="count" type="number" min="2" max="64" value="${o.positions?.length||o.count||8}"></label>`;
   else html+=`<label>偏移距离<input data-distances value="${esc((o.distances||[0,5,10]).join(', '))}"></label><label>转角<select data-field="join_style">${[['round','圆角'],['bevel','斜角'],['miter','尖角']].map(([v,l])=>`<option value="${v}" ${v===(o.join_style||'round')?'selected':''}>${l}</option>`).join('')}</select></label>`;
  }
  if(row.kind==='instances'){
   html+=`<label>状态<select data-field="state">${[['linked','关联'],['locked','锁定'],['detached','解除关联']].map(([v,l])=>`<option value="${v}" ${v===(o.state||'linked')?'selected':''}>${l}</option>`).join('')}</select></label>`;
  }
  if(o.matrix||o.matrix_step){
   html+='<div class="graphics-matrix">'+(o.matrix||o.matrix_step).map((v,i)=>`<label>${['a','b','c','d','x','y'][i]}<input type="number" step="0.05" data-matrix="${i}" value="${v}"></label>`).join('')+'</div>';
  }
  if(o.commands){
   html+='<div class="graphics-points">'+o.commands.map((c,i)=>`<div><span>${c[0]}</span>${c.slice(1).map((v,j)=>`<input type="number" aria-label="${esc(o.id)} ${i} ${j}" step="1" data-point="${i},${j+1}" value="${v}">`).join('')}</div>`).join('')+'</div>';
  }
  const style=o.style||o.style_override;
  if(style){
   for(const field of ['fill','line'])if(style[field])html+=`<label>${field==='fill'?'填充':'描边'}<input type="color" data-paint="${field}" value="#${style[field]}"></label>`;
   if(style.line||style.line_gradient)html+=`<label>线宽<input type="number" min="0.05" max="50" step="0.25" data-width value="${style.line_width_pt||1}"></label>`;
   for(const key of ['gradient','line_gradient'])if(style[key]){
    const g=style[key];
    if(g.type==='linear')html+=`<label>${key==='gradient'?'填充角度':'描边角度'}<input type="number" min="0" max="359.999" data-angle="${key}" value="${g.angle_deg}"></label>`;
    html+=g.stops.map((s,i)=>`<div class="graphics-stop"><input aria-label="色标颜色" type="color" data-stop="${key},${i},color" value="#${s.color}"><input aria-label="色标位置" type="number" min="0" max="1" step="0.01" data-stop="${key},${i},position" value="${s.position}"><input aria-label="色标透明度" type="number" min="0" max="1" step="0.05" data-stop="${key},${i},alpha" value="${s.alpha??1}"></div>`).join('');
   }
  }
  if(o.loops)html+=`<ul class="graphics-relations">${o.loops.flat().map(r=>`<li>${esc(r.edge)} ${r.reverse?'←':'→'}</li>`).join('')}</ul>`;
  $('#graphics-properties').innerHTML=html;
 }
 async function run(fn){
  if(busy)return;busy=true;main.querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=true);
  try{await fn();}catch(e){state(e.message,true);}
  finally{busy=false;if(generation===epoch)main.querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=false);}
 }
 async function preview(){
  const id=++request;state('正在计算');
  const out=await api('graphics.preview',{recipe,...(version?{version,project:$('#graphics-project').value.trim()}:{})});
  if(generation!==epoch||id!==request)return;
  $('#graphics-image').src=out.preview;state(`${out.objects.length} 个对象 · Office 未验证`);
 }
 $('#graphics-properties').onchange=e=>{
  try{
   const o=current().value,t=e.target;const style=o.style||o.style_override;
   if(t.dataset.field){
    const k=t.dataset.field;
    if(k==='mode'){
     for(const key of ['target','count','positions','matrix_step','distances','tolerance','join_style','miter_limit'])delete o[key];
     o.mode=t.value;
     if(o.mode==='interpolate'){o.target=recipe.paths.find(p=>p.id!==o.source)?.id||o.source;o.count=8;}
     if(o.mode==='affine_repeat'){o.matrix_step=[1,0,0,1,0,5];o.count=8;}
     if(o.mode==='offset')o.distances=[0,5,10];
    }else{o[k]=t.type==='number'?Number(t.value):t.value;if(k==='count')delete o.positions;}
   }
   if(t.hasAttribute('data-distances')){const values=t.value.split(',').map(v=>Number(v.trim()));if(values.some(v=>!Number.isFinite(v)))throw Error('偏移距离需要数字');o.distances=values;}
   if(t.dataset.matrix!==undefined)(o.matrix||o.matrix_step)[Number(t.dataset.matrix)]=Number(t.value);
   if(t.dataset.point){const [i,j]=t.dataset.point.split(',').map(Number);o.commands[i][j]=Number(t.value);}
   if(t.dataset.paint){style[t.dataset.paint]=t.value.slice(1).toUpperCase();delete style[t.dataset.paint==='fill'?'gradient':'line_gradient'];}
   if(t.hasAttribute('data-width'))style.line_width_pt=Number(t.value);
   if(t.dataset.angle)style[t.dataset.angle].angle_deg=Number(t.value);
   if(t.dataset.stop){const [key,i,field]=t.dataset.stop.split(',');style[key].stops[Number(i)][field]=field==='color'?t.value.slice(1).toUpperCase():Number(t.value);}
   sync();state('参数已修改');
  }catch(err){state(err.message,true);}
 };
 $('#graphics-object').onchange=properties;
 $('#graphics-preview').onclick=()=>run(preview);
 $('#graphics-apply').onclick=()=>run(async()=>{recipe=JSON.parse($('#graphics-json').value);sync();await preview();});
 $('#graphics-copy').onclick=()=>copy(JSON.stringify(recipe,null,2));
 $('#graphics-save').onclick=()=>run(async()=>{
  const project=$('#graphics-project').value.trim();if(!project)throw Error('请选择已授权项目目录');
  const out=await api(version?'graphics.regenerate':'graphics.compile',{project,recipe,...(version?{version}:{})});
  if(generation!==epoch)return;
  version=out.version;$('#graphics-version').value=version;
  $('#graphics-result').textContent=out.pptx;
  state('原生草稿已生成 · 尚未采用');
 });
 $('#graphics-load').onclick=()=>run(async()=>{
  const project=$('#graphics-project').value.trim(),candidate=$('#graphics-version').value.trim();
  const out=await api('graphics.inspect',undefined,{project,version:candidate});
  if(generation!==epoch)return;
  version=candidate;recipe=out.recipe;sync();
  if(out.manual_conflicts?.length)state('检测到 PPT 手工修改，原稿已保留',true);
  else await preview();
 });
 $('#graphics-fit').onclick=()=>run(async()=>{
  const file=$('#graphics-input').files[0],mask=$('#graphics-mask').files[0];if(!file)throw Error('请选择区域图像');
  if(file.size>6_000_000||(mask&&mask.size>6_000_000))throw Error('图像文件过大');
  const channel=$('#graphics-channel').value;
  if(channel==='line'&&$('#graphics-model').value==='radial')throw Error('描边仅支持线性渐变');
  const out=await api('graphics.fit_gradient',{image:await readFile(file),...(mask?{mask:await readFile(mask)}:{}),
   models:[$('#graphics-model').value],max_stops:Number($('#graphics-stops').value)});
  if(generation!==epoch)return;
  const o=current().value;
  if(!['paths','faces','curve_groups','instances'].includes(current().kind))throw Error('请选择可设置填充的对象');
  const key=current().kind==='instances'?'style_override':'style';
  o[key]={...(o[key]||{})};
  if(channel==='line'){
   delete o[key].line_alpha;delete o[key].line_gradient;
   if(out.style.gradient)o[key].line_gradient=out.style.gradient;
   else o[key].line=out.style.fill;
  }else{
   delete o[key].fill_alpha;delete o[key].gradient;
   Object.assign(o[key],out.style);
  }
  sync();$('#graphics-fit-result').textContent=`验证误差 ${out.selected.validation_mae.toFixed(4)} · ${out.validation_samples} 个采样点 · 不透明颜色`;
  state('渐变参数已更新');
 });
 sync();await run(preview);
}
