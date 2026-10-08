import {api,copy} from './api.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0;
export function stopIcons(){generation++;}
export async function mountIcons(main){
 const epoch=++generation;let serial=0,selected=null,reference='';
 const current=()=>epoch===generation;
 main.innerHTML=`<section class="icon-library"><div class="page-head"><h1>图形素材</h1><button id="icons-refresh">刷新</button></div>
 <p id="icons-message" role="status"></p>
 <div class="icons-toolbar"><input id="icons-query" type="search" aria-label="搜索素材" placeholder="搜索名称或标签"><select id="icons-collection" aria-label="素材库"><option value="">全部素材</option></select><select id="icons-style" aria-label="风格"><option value="">全部风格</option><option value="outline">线性</option><option value="filled">填充</option><option value="multicolor">多色</option></select><label><input id="icons-drafts" type="checkbox">包含待检查素材</label><button id="icons-search">搜索</button></div>
 <div class="icons-layout"><div><div class="icons-reference"><label>参考图<input id="icons-reference" type="file" accept="image/png,image/jpeg,image/webp"></label><button id="icons-similar">按外观查找</button><button id="icons-clear">清除参考图</button></div><p id="icons-count"></p><div id="icons-grid" class="icons-grid"></div></div><aside id="icons-detail" class="icons-detail"><p>未选择素材</p></aside></div></section>`;
 const $=s=>main.querySelector(s);
 const message=(t,bad=false)=>{if(current()){$('#icons-message').textContent=t;$('#icons-message').className=bad?'error-banner':'small muted';}};
 const run=async fn=>{try{await fn();}catch(e){message(e.message,true);}};
 async function search(similar=false){
  const turn=++serial,collection=$('#icons-collection').value;
  const data=await api('icons.search',{query:$('#icons-query').value,collection,style:$('#icons-style').value,
   include_drafts:$('#icons-drafts').checked||collection==='Agent 自绘',limit:100,...(similar&&reference?{reference}:{})});
  if(!current()||turn!==serial)return;
  $('#icons-count').textContent=`${data.total} 个素材${data.total>100?' · 显示前 100 个':''}`;
  $('#icons-grid').innerHTML=data.items.map(x=>`<button class="icon-card" data-version="${esc(x.version)}"><img src="${x.preview}" alt=""><strong>${esc(x.metadata.name)}</strong><span>${esc(x.metadata.collection)}</span><small>${x.status==='draft'?'已保存 · 待检查':x.status==='rejected'?'检查未通过':x.status==='curated'?'精选素材':'已检查'}</small></button>`).join('')||'<p class="icons-empty">暂无匹配素材</p>';
  message('');
 }
 async function select(version){
  selected=version;
  const [x,projects]=await Promise.all([api('icons.inspect',undefined,{version}),api('workbench.projects')]);
  if(!current()||selected!==version)return;
  $('#icons-detail').innerHTML=`<img class="icon-large" src="${x.preview}" alt=""><h2>${esc(x.metadata.name)}</h2><p>${esc(x.metadata.author)} · ${esc(x.metadata.license)}</p><p class="small">${esc(x.metadata.notes||x.metadata.source_url||'')}</p>
  <label>目标项目<select id="icon-project"><option value="">选择项目</option>${projects.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')}</select></label>
  <label>统一颜色<input id="icon-color" type="color" value="#315fee"></label><label><input id="icon-recolor" type="checkbox">应用统一颜色</label>
  <div class="actions"><button id="icon-place">加入项目</button><button id="icon-copy">复制原生对象</button><button id="icon-attribution">复制署名</button></div>
  <details><summary>验证记录</summary><pre>${esc(JSON.stringify(x.reviews,null,2))}</pre></details>
  <label>检查说明<textarea id="icon-review-note"></textarea></label><div class="actions"><button id="icon-approve">检查通过</button><button id="icon-reject">检查未通过</button></div>`;
  const options=()=>({version,...($('#icon-recolor').checked?{color:$('#icon-color').value.slice(1)}:{})});
  $('#icon-place').onclick=()=>run(async()=>{if(!$('#icon-project').value)throw Error('请选择项目');const r=await api('icons.place',{...options(),project_key:$('#icon-project').value});message('已加入 '+r.directory);});
  $('#icon-copy').onclick=()=>run(async()=>{await copy(JSON.stringify(await api('icons.fragment',options()),null,2));message('已复制');});
  $('#icon-attribution').onclick=()=>run(async()=>{await copy(x.attribution.text);message('已复制署名');});
  for(const [id,decision] of [['icon-approve','approve'],['icon-reject','reject']]){
   $('#'+id).onclick=()=>run(async()=>{await api('icons.review',{version,decision,note:$('#icon-review-note').value});await select(version);await search();});
  }
 }
 async function refresh(){
  const stats=await api('icons.stats');if(!current())return;
  const previous=$('#icons-collection').value;
  $('#icons-collection').innerHTML='<option value="">全部素材</option>'+[...new Set(['Agent 自绘',...stats.collections])].map(c=>`<option>${esc(c)}</option>`).join('');
  $('#icons-collection').value=previous;await search();
 }
 $('#icons-grid').onclick=e=>{const b=e.target.closest('[data-version]');if(b)run(()=>select(b.dataset.version));};
 $('#icons-search').onclick=()=>run(()=>search());
 $('#icons-refresh').onclick=()=>run(refresh);
 $('#icons-query').onkeydown=e=>{if(e.key==='Enter')run(()=>search());};
 for(const id of ['icons-collection','icons-style','icons-drafts'])$('#'+id).onchange=()=>run(()=>search());
 $('#icons-reference').onchange=()=>run(async()=>{const f=$('#icons-reference').files[0];if(!f)return;if(f.size>5000000)throw Error('参考图不能超过 5MB');reference=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f);});});
 $('#icons-similar').onclick=()=>run(async()=>{if(!reference)throw Error('请选择参考图');await search(true);});
 $('#icons-clear').onclick=()=>{reference='';$('#icons-reference').value='';};
 await run(refresh);
}
