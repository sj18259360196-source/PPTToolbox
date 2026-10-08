import {api} from './api.js';
let cached=null,pending=null;
export async function projectIndex(fresh=false){
 if(cached&&!fresh)return cached;
 if(pending)return pending;
 pending=api('projects.index').then(value=>(cached=value)).finally(()=>pending=null);
 return pending;
}
// A long-held, authenticated request only returns rows when metadata changed.
// No project-file scan or periodic DOM replacement is involved.
export function watchProjectIndex(onChange,onError){
 const controller=new AbortController();let retry;
 async function listen(){
  while(!controller.signal.aborted){
   try{
    const value=await api('projects.index',undefined,{since:cached?.revision||'',wait:'25'},{signal:controller.signal});
    if(controller.signal.aborted)return;
    if(value.changed){cached=value;onChange(value);}
   }catch(error){
    if(controller.signal.aborted)return;
    onError(error);await new Promise(resolve=>{retry=setTimeout(resolve,5000);});
   }
  }
 }
 listen();return ()=>{controller.abort();clearTimeout(retry);};
}
