// One polling chain per visible window. Ignore late responses after hiding.
export function visiblePolling(read,render,{doc=globalThis.document,win=globalThis.window,setTimer=setTimeout,clearTimer=clearTimeout,interval=2000}={}){
 let paused=true,closed=false,pageHidden=false,timer=null,controller=null,generation=0;
 const visible=()=>!doc.hidden&&!pageHidden&&win.__pptDesktopVisible!==false;
 function cancel(){generation++;clearTimer(timer);timer=null;controller?.abort();controller=null;}
 async function poll(){
  if(paused||closed)return;
  const current=++generation;controller=new AbortController();
  try{const data=await read(controller.signal);if(current===generation&&visible()&&!closed)render(data);}
  catch(error){if(current===generation&&visible()&&!closed&&error.name!=='AbortError')render(null);}
  finally{if(current===generation){controller=null;if(!paused&&!closed)timer=setTimer(poll,interval);}}
 }
 function sync(){
  if(closed)return;
  if(!visible()){paused=true;cancel();}
  else if(paused){paused=false;poll();}
 }
 const hide=()=>{pageHidden=true;sync();};
 const show=()=>{pageHidden=false;sync();};
 doc.addEventListener('visibilitychange',sync);
 win.addEventListener('ppt-desktop-visibility',sync);
 win.addEventListener('pagehide',hide);
 win.addEventListener('pageshow',show);
 sync();
 return ()=>{closed=true;cancel();doc.removeEventListener('visibilitychange',sync);win.removeEventListener('ppt-desktop-visibility',sync);win.removeEventListener('pagehide',hide);win.removeEventListener('pageshow',show);};
}
