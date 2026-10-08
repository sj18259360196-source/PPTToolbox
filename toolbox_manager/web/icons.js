import {usageMap,usageLink,track} from './usage.js';
import {api as requestApi,copy} from './api.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0;
export function stopIcons(){generation++;}
export async function mountIcons(main){
 const trackingProject=new URLSearchParams(location.hash.split('?')[1]||'').get('project');
 const api=(op,body,query)=>requestApi(op,body&&trackingProject?{...body,tracking_project:trackingProject}:body,body?query:{...query,...(trackingProject?{tracking_project:trackingProject}:{})});
 const epoch=++generation;
 let selected=null,variantParent=null,reference='',job=null,serial=0;
 const projectKey=new URLSearchParams(location.hash.split('?')[1]||'').get('project')||'';
 main.innerHTML=`<nav class="section-nav" aria-label="素材分类"><a href="#/icons">素材库</a><a href="#/graphics">图形构造</a></nav><section class="icon-library"><div class="page-head"><div><h1>图标素材</h1><p class="subtitle">查找、重绘和保存可编辑图标</p></div><button id="icons-refresh">刷新图标库</button></div>
 <div id="icons-message" role="status">正在载入素材包，首次载入需要一些时间…</div>
 <div class="icons-toolbar"><input id="icons-query" type="search" aria-label="搜索图标" placeholder="搜索中文名称、英文名称或标签"><select id="icons-collection" aria-label="图标库"><option value="">全部图标库</option></select><select id="icons-style" aria-label="图标风格"><option value="">全部风格</option><option value="outline">线性</option><option value="filled">填充</option><option value="multicolor">多色</option></select><label><input id="icons-drafts" type="checkbox">显示草稿</label><button id="icons-search">搜索</button></div>
 <div class="icons-layout"><div><div class="icons-reference"><label>参考图局部<input id="icons-reference" type="file" accept="image/png,image/jpeg,image/webp"></label><button id="icons-similar">按外观查找</button><button id="icons-clear-reference">清除参考图</button><img id="icons-reference-preview" hidden alt="参考图局部"></div><p id="icons-count"></p><div id="icons-grid" class="icons-grid"></div></div><aside id="icons-detail" class="icons-detail"><p>选择一个图标，查看部件、来源和验证记录。</p></aside></div>
 <details class="icons-author"><summary>自绘与导入</summary><div class="icons-author-grid"><div><label>名称<input id="icons-name" placeholder="例如细菌外形"></label><label>作者<input id="icons-author" value="用户自绘"></label><label>授权说明<input id="icons-license" value="LicenseRef-UserProvided"></label><label>标签<input id="icons-tags" placeholder="用逗号分隔，例如细菌,微生物"></label><label>重绘要求<textarea id="icons-brief" placeholder="说明含义、组成部件和需要保留的细节"></textarea></label><button id="icons-start-redraw">建立 Agent 重绘任务</button><button id="icons-trace">从参考图生成轮廓草稿</button></div><div><label>SVG 源码<textarea id="icons-svg" class="editor" spellcheck="false" placeholder="粘贴 SVG，使用 id 为部件命名"></textarea></label><div class="actions"><button id="icons-save">保存 SVG 草稿</button><button id="icons-submit">提交本次重绘</button></div><label>批量导入 SVG 或图标包<input id="icons-import-files" type="file" accept=".svg,.json" multiple></label><p class="small muted">导入保留来源信息。草稿通过人工检查后才会进入默认搜索。</p></div></div></details>
 <details class="icons-author"><summary>可选 SVG 模型服务</summary><p>连接本机提供 SVG 输出的模型服务。输入和输出协议见图标使用手册。</p><label>服务名称<input id="icons-provider-name" placeholder="例如 StarVector 本机服务"></label><label>本机接口地址<input id="icons-provider-url" placeholder="http://127.0.0.1:端口/generate"></label><button id="icons-provider-save">保存连接</button><button id="icons-model-generate">按重绘要求生成草稿</button><p id="icons-provider-status"></p></details></section>`;
 const $=s=>main.querySelector(s);
 const message=(text,error=false)=>{if(epoch!==generation)return;$('#icons-message').textContent=text;$('#icons-message').className=error?'error-banner':'notice';};
 async function run(fn){try{await fn();}catch(e){message(e.message,true);}}
 const meta=()=>({name:$('#icons-name').value.trim(),author:$('#icons-author').value.trim(),license:$('#icons-license').value.trim(),tags:$('#icons-tags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean),aliases:[],collection:'个人图标',style:'multicolor',origin:'self_drawn'});
 async function search(similar=false){
  const turn=++serial;
  const counts=await usageMap('icon');
  const data=await api('icons.search',{query:$('#icons-query').value,collection:$('#icons-collection').value,style:$('#icons-style').value,include_drafts:$('#icons-drafts').checked,limit:100,...(similar&&reference?{reference}:{})});
  if(epoch!==generation||turn!==serial)return;
  $('#icons-count').textContent=`找到 ${data.total} 个图标${data.total>100?'，显示前 100 个':''}`;
  $('#icons-grid').innerHTML=data.items.length?data.items.map(x=>`<button class="icon-card" data-version="${x.version}" aria-label="选择 ${esc(x.metadata.name)}"><img src="${x.preview}" alt=""><strong>${esc(x.metadata.name)}</strong><span>${esc(x.metadata.collection)} · ${x.part_count} 个部件</span><small>${counts[x.version]?.counts?.extracted||0} 次提取 · ${counts[x.version]?.counts?.placed||0} 次加入项目 · ${x.status==='draft'?'待检查草稿':x.status==='rejected'?'检查未通过':x.status==='curated'?'精选素材':'已人工检查'}</small></button>`).join(''):'<p class="icons-empty">没有匹配的图标。可换个关键词，或在下方建立重绘任务。</p>';
  message(similar?'已按外观排序，请核对图标含义。':'图标库已载入');
 }
 async function select(version){
  const x=await api('icons.inspect',undefined,{version});if(epoch!==generation)return;selected=x;
  await track('icon',version,'viewed');const counts=await usageMap('icon');
  $('#icons-detail').innerHTML=`<img class="icon-large" src="${x.preview}" alt="${esc(x.metadata.name)}"><h2>${esc(x.metadata.name)}</h2>${usageLink('icon',version,counts[version])}<p>${x.part_count} 个原生路径部件 · ${x.node_count} 个节点</p><p>${esc(x.metadata.author)} · ${esc(x.metadata.license)}</p><p class="small">${esc(x.metadata.source_url||'用户自绘素材')}</p><label>统一颜色<input id="icon-color" type="color" value="#315fee"></label><label><input id="icon-recolor" type="checkbox">应用统一颜色</label><label>描边宽度<input id="icon-width" type="number" min="0.1" max="100" step="0.1" placeholder="保留原线宽"></label><label>目标项目<select id="icon-project"><option value="">请选择项目</option></select></label><div class="actions"><button id="icon-place">加入项目素材</button><button id="icon-copy">复制原生对象 JSON</button><button id="icon-variant">编辑为新版本</button></div><details><summary>转换验证记录</summary><pre>${esc(JSON.stringify(x.reviews,null,2))}</pre></details><label>检查说明<textarea id="icon-review-note" placeholder="核对轮廓、部件及含义，记录发现的问题"></textarea></label><div class="actions"><button id="icon-approve">通过检查并加入常用库</button><button id="icon-reject">标记未通过</button></div><p class="small muted">图标检查与放入具体幻灯片后的 PowerPoint 验证分别记录。</p>`;
  const options=()=>({version,...($('#icon-recolor').checked?{color:$('#icon-color').value.slice(1)}:{}),...($('#icon-width').value?{stroke_width:Number($('#icon-width').value)}:{})});
  $('#icon-copy').insertAdjacentHTML('afterend','<button id="icon-attribution">复制素材署名</button>');
  $('#icon-attribution').onclick=()=>run(async()=>{await copy(x.attribution?.text||[x.metadata.name,x.metadata.author,x.metadata.license,x.metadata.source_url,x.metadata.source_revision].filter(Boolean).join('\n'));message('已复制素材署名，交付时请保留来源及修改说明');});
  $('#icon-place').onclick=()=>run(async()=>{if(!$('#icon-project').value)throw Error('请选择目标项目');const r=await api('icons.place',{...options(),project_key:$('#icon-project').value});message('已保存原生 PPTX 和配方到 '+r.directory+'。Agent 可在当前任务中放置到页面。');});
  $('#icon-copy').onclick=()=>run(async()=>{const r=await api('icons.fragment',options());await copy(JSON.stringify(r,null,2));message('已复制原生对象分组和来源信息');});
  $('#icon-variant').onclick=()=>{variantParent=x;$('#icons-name').value=x.metadata.name;$('#icons-svg').value=x.svg;$('#icons-tags').value=x.metadata.tags.join(',');$('#icons-author').value=x.metadata.author;$('#icons-license').value=x.metadata.license;$('.icons-author').open=true;message('修改后保存会生成新版本，保留来源和父版本');};
  for(const [id,decision] of [['icon-approve','approve'],['icon-reject','reject']])$('#'+id).onclick=()=>run(async()=>{await api('icons.review',{version,decision,note:$('#icon-review-note').value});await select(version);await search();message('已保存人工检查结论');});
  const projects=await api('workbench.projects');if(epoch!==generation||selected?.version!==version)return;
  $('#icon-project').insertAdjacentHTML('beforeend',projects.map(p=>`<option value="${esc(p.id)}" ${p.id===projectKey?'selected':''}>${esc(p.label)}</option>`).join(''));
 }
 $('#icons-grid').onclick=e=>{const card=e.target.closest('[data-version]');if(card)run(()=>select(card.dataset.version));};
 $('#icons-search').onclick=()=>run(()=>search());$('#icons-refresh').onclick=()=>run(async()=>{
  const stats=await api('icons.stats');if(epoch!==generation)return;
  const current=$('#icons-collection').value;
  $('#icons-collection').innerHTML='<option value="">全部图标库</option>'+stats.collections.map(c=>`<option>${esc(c)}</option>`).join('');
  if(stats.collections.includes(current))$('#icons-collection').value=current;
  await search();
 });
 $('#icons-query').onkeydown=e=>{if(e.key==='Enter')run(()=>search());};
 for(const id of ['icons-collection','icons-style','icons-drafts'])$('#'+id).onchange=()=>run(()=>search());
 $('#icons-reference').onchange=()=>run(async()=>{const f=$('#icons-reference').files[0];if(!f)return;if(f.size>5_000_000)throw Error('参考图请控制在 5MB 内');reference=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f);});$('#icons-reference-preview').src=reference;$('#icons-reference-preview').hidden=false;message('已载入参考图局部');});
 $('#icons-clear-reference').onclick=()=>{reference='';$('#icons-reference').value='';$('#icons-reference-preview').hidden=true;};
 $('#icons-similar').onclick=()=>run(async()=>{if(!reference)throw Error('请先选择参考图局部');await search(true);});
 $('#icons-start-redraw').onclick=()=>run(async()=>{const r=await api('icons.redraw_start',{brief:$('#icons-brief').value,...(reference?{reference}:{})});job=r.job;await copy(JSON.stringify(r,null,2));message('已建立重绘任务并复制 Agent 指令。完成 SVG 后可提交，最多三次。');});
 async function saved(r){const item=r.icon||r;$('#icons-drafts').checked=true;await search();await select(item.version);message('已保存草稿。请检查后决定是否加入常用库。');}
 $('#icons-save').onclick=()=>run(async()=>{const metadata=meta();if(variantParent){metadata.origin=variantParent.metadata.origin;metadata.source_url=variantParent.metadata.source_url||'';metadata.source_revision=variantParent.metadata.source_revision||'';}await saved(await api('icons.import',{svg:$('#icons-svg').value,metadata,...(variantParent?{parent:variantParent.version}:{}),...(reference?{reference}:{})}));});
 $('#icons-submit').onclick=()=>run(async()=>{if(!job)throw Error('请先建立重绘任务');await saved(await api('icons.redraw_submit',{job,svg:$('#icons-svg').value,metadata:meta()}));});
 $('#icons-trace').onclick=()=>run(async()=>{if(!reference)throw Error('请先选择参考图局部');message('正在生成轮廓草稿…');await saved(await api('icons.trace',{reference,metadata:meta()}));});
 $('#icons-import-files').onchange=()=>run(async()=>{const files=Array.from($('#icons-import-files').files);if(files.length>50)throw Error('每批最多选择 50 个文件');let items=[];for(const file of files){if(file.size>400000)throw Error(file.name+' 超过 400KB');const text=await file.text();if(file.name.endsWith('.json')){const pack=JSON.parse(text);items.push(...(pack.items||pack));}else items.push({svg:text,metadata:{...meta(),name:file.name.replace(/\.svg$/i,'')}});}const r=await api('icons.batch',{items});$('#icons-drafts').checked=true;await search();message(`导入成功 ${r.passed} 个，失败 ${r.failed} 个。`+r.items.filter(x=>!x.ok).map(x=>`第 ${x.index+1} 项 ${x.error}`).join('；'),r.failed>0);});
 $('#icons-provider-save').onclick=()=>run(async()=>{await api('icon-provider.save',{name:$('#icons-provider-name').value,endpoint:$('#icons-provider-url').value});message('已保存本机模型接口');});
 $('#icons-model-generate').onclick=()=>run(async()=>{message('正在请求本机模型…');await saved(await api('icons.model_generate',{brief:$('#icons-brief').value,metadata:meta(),...(reference?{reference}:{})}));});
 await run(async()=>{const [stats,providers]=await Promise.all([api('icons.stats'),api('icons.providers')]);if(epoch!==generation)return;$('#icons-collection').insertAdjacentHTML('beforeend',stats.collections.map(c=>`<option>${esc(c)}</option>`).join(''));$('#icons-provider-status').textContent=`VTracer ${providers.vtracer.available?'可用':'未安装'} · SVG 模型${providers.svg_model.configured?'已配置，实际效果需验证':'未配置'}`;await search();});
}
