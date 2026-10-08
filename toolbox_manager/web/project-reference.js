import {createImageViewer} from './project-image-viewer.js';
import {api} from './api.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function mountProjectReference(panel,project){
 let disposed=false,busy=false,pages=[],page=0,serial=0,signature='',url='';const viewer=createImageViewer(panel);
 const alive=()=>!disposed&&panel.isConnected;
 async function image(item,full=false){
  const response=await fetch('/api/project.preview?'+new URLSearchParams({project,path:item.path,full:full?'1':'0'}),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
  if(!response.ok)throw Error('参考图读取失败');return response.blob();
 }
 async function paint(){
  viewer.close();
  const request=++serial,item=pages[page];
  panel.innerHTML=`<button class="chain-reference-image" aria-label="放大参考图"><img alt="${esc(item.name)}"></button><div class="chain-media-footer"><span title="${esc(item.path)}">${esc(item.name)}</span><div class="simple-preview-pager"><button data-prev aria-label="上一张参考图" ${page===0?'disabled':''}>‹</button><span>${page+1} / ${pages.length}</span><button data-next aria-label="下一张参考图" ${page===pages.length-1?'disabled':''}>›</button></div></div><div class="chain-media-actions"><span class="small muted" role="status">点击图片放大查看</span><button data-enlarge>放大参考图</button></div>`;
  panel.querySelector('[data-prev]').onclick=()=>{page--;paint().catch(fail);};
  panel.querySelector('[data-next]').onclick=()=>{page++;paint().catch(fail);};
  panel.querySelector('.chain-reference-image').onclick=async()=>{
   try{
    const blob=await image(item,true);if(!alive()||request!==serial)return;
    await viewer.open('参考图 · '+item.name,async()=>blob);
   }catch(error){fail(error);}
  };
  panel.querySelector('[data-enlarge]').onclick=()=>panel.querySelector('.chain-reference-image').click();
  const blob=await image(item,true);if(!alive()||request!==serial)return;
  if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);panel.querySelector('.chain-reference-image img').src=url;
 }
 function fail(error){if(alive()){signature='';const status=panel.querySelector('[role=status]');if(status)status.textContent=error.message;else panel.textContent=error.message;}}
 async function refresh(){
  if(!alive()||busy)return;busy=true;
  try{
   const result=await api('project.gallery',undefined,{project});if(!alive())return;
   const next=result.versions.filter(v=>v.kind==='参考图').flatMap(v=>v.pages),nextSignature=JSON.stringify(next);
   if(signature===nextSignature)return;
   const previous=pages[page]?.path;pages=next;page=Math.max(0,pages.findIndex(p=>p.path===previous));
   if(pages.length)await paint();else{serial++;if(url)URL.revokeObjectURL(url);url='';panel.innerHTML='<div class="simple-preview-empty">项目 input 文件夹中暂无参考图</div>';}
   if(alive())signature=nextSignature;
  }catch(error){fail(error);}finally{busy=false;}
 }
 panel.innerHTML='<div class="simple-preview-empty" role="status">正在读取参考图…</div>';
 return {refresh,dispose(){disposed=true;serial++;viewer.dispose();if(url)URL.revokeObjectURL(url);}};
}
