import {mountGallery,mountMaterialPolicy,clearProjectMedia} from './project-media.js';
import {api,copy} from './api.js';
import {mountProjectFiles} from './project-file-browser.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0;
export function stopProjectDetails(){generation++;clearProjectMedia();}
export function mountProjectDetails(main){
 const epoch=++generation,wb=main.querySelector('.wb');if(!wb)return;
 const nav=document.createElement('div');nav.className='workspace-tabs';nav.setAttribute('role','tablist');
 nav.innerHTML=['制作','任务预览','项目文件','素材权限','交付与反馈','活动记录'].map((x,i)=>`<button role="tab" aria-selected="${!i}" data-workspace-tab="${x}">${x}</button>`).join('');
 wb.querySelector('.wb-header').after(nav);
 const panel=document.createElement('section');panel.className='project-extra';panel.hidden=true;wb.append(panel);
 let serial=0;
 nav.onclick=async e=>{
  const b=e.target.closest('[data-workspace-tab]');if(!b)return;
  const tab=b.dataset.workspaceTab,request=++serial;panel.dataset.request=String(request);nav.querySelectorAll('button').forEach(x=>x.setAttribute('aria-selected',String(x===b)));
  wb.querySelector('.wb-layout').hidden=tab!=='制作';wb.querySelector('.wb-events').hidden=tab!=='制作';panel.hidden=tab==='制作';
  if(tab==='制作')return;panel.innerHTML='<p>正在读取项目…</p>';
  try{
   const project=new URLSearchParams(location.hash.split('?')[1]||'').get('project');if(!project)throw Error('请先选择已登记项目');
   if(tab==='任务预览'){await mountGallery(panel,project);return;}
   if(tab==='素材权限'){await mountMaterialPolicy(panel,project);return;}
   if(tab==='项目文件'||tab==='交付与反馈'){
    const fileData=await mountProjectFiles(panel,project,tab==='交付与反馈');
    if(tab==='交付与反馈'&&fileData&&epoch===generation&&request===serial){
     const assets=await api('project.files',undefined,{project,group:'assets',limit:500});
     if(epoch===generation&&request===serial)await feedback(panel.querySelector('#retrospective-panel'),project,{...fileData,files:assets.files});
    }
    return;
   }
   const data=await api('project.files',undefined,{project});if(epoch!==generation||request!==serial)return;
   const files=tab==='交付与反馈'?data.files.filter(f=>f.group==='delivery'):data.files;
   panel.innerHTML=tab==='活动记录'?`<section class="panel panel-body"><h2>工作流活动</h2>${data.history.length?data.history.map(h=>`<details class="history-record"><summary>${esc(h.at||h.time||'')} · ${esc(h.action||h.event||h.kind||'工作流记录')}</summary><pre>${esc(JSON.stringify(h,null,2))}</pre></details>`).join(''):'<p class="muted">暂无工作流历史，受管调用记录可在制作页下方查看。</p>'}</section>`:`<section class="panel panel-body"><div class="section-title"><h2>${tab==='交付与反馈'?'交付文件':'项目文件'}</h2><button id="detail-copy">打开项目文件夹</button></div><p class="path-block">${esc(data.root)}</p>${files.length?`<div class="file-list">${files.map(f=>`<div class="file-row"><div><strong>${esc(f.name)}</strong><small>${esc(f.path)} · ${(f.size/1024).toFixed(1)} KB</small></div><div class="file-actions"><button class="primary" data-open-file="${esc(f.path)}">打开</button><button data-reveal-file="${esc(f.path)}">打开所在文件夹</button><details><summary>更多</summary><button data-download="${esc(f.path)}">另存副本</button></details></div></div>`).join('')}</div>`:'<p class="empty">暂无项目文件。</p>'}${data.limited?'<p>清单最多展示 500 个文件，请到项目目录查看其余内容。</p>':''}</section>${tab==='交付与反馈'?'<section class="panel panel-body" id="retrospective-panel"><p>正在读取交付记录…</p></section>':''}<p id="detail-status" role="status"></p>`;
   const message=t=>{if(panel.querySelector('#detail-status'))panel.querySelector('#detail-status').textContent=t};
   if(panel.querySelector('#detail-copy'))panel.querySelector('#detail-copy').onclick=()=>api('project.open',{project,action:'reveal'}).then(()=>message('已请求打开项目文件夹')).catch(e=>message(e.message));
   panel.querySelectorAll('[data-open-file],[data-reveal-file]').forEach(button=>button.onclick=async()=>{try{await api('project.open',{project,path:button.dataset.openFile||button.dataset.revealFile,action:button.hasAttribute('data-reveal-file')?'reveal':'open'});message('已请求本机程序打开');}catch(e){message(e.message);}});
   panel.querySelectorAll('[data-download]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const r=await fetch('/api/project.file?'+new URLSearchParams({project,path:button.dataset.download}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=button.dataset.download.split('/').at(-1);a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){message(e.message)}finally{button.disabled=false}});
   if(tab==='交付与反馈')await feedback(panel.querySelector('#retrospective-panel'),project,data);
  }catch(e){if(epoch===generation&&request===serial)panel.innerHTML=`<div class="error-banner">${esc(e.message)}</div>`;}
 };
}

async function feedback(panel,project,data){
 if(data.lifecycle?.history_cleaned){panel.innerHTML='<h2>制作历史已清理</h2><p>原流程的验收与反馈不再继续写入。保留的成品仍可打开和编辑。</p>';return;}
 if(data.status!=='delivered'){panel.innerHTML='<h2>等待正式交付</h2><p>请由 Agent 完成工作流检查与交付，再记录成品认可、素材保留和制作经验。</p>';return;}
 let record;
 try{record=await api('retrospective',{action:'status',project})}catch(e){panel.textContent=e.message;return;}
 const step=!record.presented?'presented':!record.accept?'accept':!record.assets?'assets':!record.consent?'consent':record.consent.learn&&!record.report?'submit':'done';
 const labels={presented:'确认成品已经展示',accept:'记录成品认可',assets:'选择保留的自绘素材',consent:'是否记录本次经验',submit:'填写制作经验',done:'交付反馈已记录'};
 panel.innerHTML=`<h2>${labels[step]}</h2><p class="small muted">决定绑定当前交付版本。已记录的认可与同意保留原文，不自动推定下一步。</p>${step==='done'?`<p>${record.report?'制作经验已进入经验库。':'已记录本次决定。'}</p><a href="#/learning">查看经验库</a>`:step==='submit'?['worked','failed','evidence','applicability'].map((k,i)=>`<label>${['做得好的地方','问题与失败','验证依据','适用范围'][i]}<textarea data-report="${k}" required></textarea></label>`).join(''):`<label>${step==='presented'?'展示说明':'你的决定与反馈'}<textarea id="feedback-reply" required></textarea></label>${step==='assets'?data.files.filter(f=>f.path.endsWith('.svg')&&f.group==='assets').map(f=>`<label class="asset-consent"><input type="checkbox" data-retain="${esc(f.path)}">${esc(f.name)}<input data-license="${esc(f.path)}" placeholder="许可说明，保留时必填"></label>`).join('')+'<p>不勾选则本次不保留素材。保留前请核对来源与许可。</p>':''}${step==='consent'?'<label><input id="feedback-learn" type="checkbox">同意记录本次经验</label>':''}`}${step!=='done'?'<button id="feedback-submit" class="primary">保存本次决定</button>':''}<p id="feedback-error" role="alert"></p>`;
 if(step==='done')return;
 panel.querySelector('#feedback-submit').onclick=async e=>{
  e.target.disabled=true;
  try{
   const reply=panel.querySelector('#feedback-reply')?.value.trim();let body={action:step,project};
   if(step==='submit'){body.report={};for(const t of panel.querySelectorAll('[data-report]')){if(!t.value.trim())throw Error('请填写各项经验和验证依据');body.report[t.dataset.report]=t.value.trim().split('\n').filter(Boolean)}}
   else{if(!reply)throw Error('请填写本次决定或展示说明');body[step==='presented'?'message':'user_reply']=reply;}
   if(step==='assets'){body.files=[...panel.querySelectorAll('[data-retain]:checked')].map(c=>{const license=[...panel.querySelectorAll('[data-license]')].find(x=>x.dataset.license===c.dataset.retain).value.trim();if(!license)throw Error('保留素材需要许可说明');return {path:c.dataset.retain,name:c.dataset.retain.split('/').at(-1),license}})}
   if(step==='consent')body.learn=panel.querySelector('#feedback-learn').checked;
   await api('retrospective',body);await feedback(panel,project,data);
  }catch(err){panel.querySelector('#feedback-error').textContent=err.message;e.target.disabled=false;}
 };
}
