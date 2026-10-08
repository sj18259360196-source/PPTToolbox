// Keep only nearby rows decoded, with at most three downloads in flight.
export function projectThumbnails(host){
 let disposed=false,active=0;const states=new Map();
 const observer=new IntersectionObserver(entries=>{
  for(const {target,isIntersecting} of entries){
   const state=states.get(target);if(!state)continue;state.visible=isIntersecting;
   if(!isIntersecting){state.controller?.abort();release(target,state);}
  }
  pump();
 },{rootMargin:'160px'});
 function release(element,state){if(state.url){URL.revokeObjectURL(state.url);state.url='';element.querySelector('img')?.remove();}}
 function pump(){
  if(disposed)return;
  for(const [element,state] of states){
   if(active>=3)break;
   if(!state.visible||state.url||state.controller||state.empty)continue;
   active++;const controller=new AbortController();state.controller=controller;
   fetch('/api/project.thumbnail?'+new URLSearchParams({project:element.dataset.thumbnail}),{
    headers:{Authorization:'Bearer '+(sessionStorage.getItem('ppt-manager-token')||'')},signal:controller.signal
   }).then(async response=>{
    if(response.status===204){state.empty=true;element.querySelector('span').textContent='暂无参考图';return;}
    if(!response.ok)throw Error('thumbnail');
    const blob=await response.blob();if(disposed||!state.visible||!element.isConnected||controller.signal.aborted)return;
    state.url=URL.createObjectURL(blob);const img=new Image();img.alt='参考图缩略图';img.decoding='async';img.src=state.url;element.append(img);
   }).catch(error=>{if(error.name!=='AbortError'){state.empty=true;element.querySelector('span').textContent='缩略图暂不可用';}})
    .finally(()=>{state.controller=null;active--;pump();});
  }
 }
 function clear(){observer.disconnect();for(const [element,state] of states){state.controller?.abort();release(element,state);}states.clear();}
 return {paint(){clear();for(const element of host.querySelectorAll('[data-thumbnail]')){states.set(element,{visible:false,url:'',controller:null,empty:false});observer.observe(element);}},dispose(){disposed=true;clear();}};
}
