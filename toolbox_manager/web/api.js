const desktopVisibility=new URLSearchParams(location.search).get('desktop_visible');
if(desktopVisibility!==null)window.__pptDesktopVisible=desktopVisibility==='1';
window.addEventListener('hashchange',()=>{if(location.hash.startsWith('#token=')){sessionStorage.setItem('ppt-manager-token',decodeURIComponent(location.hash.slice(7)));history.replaceState(null,'','#/overview');}});
const fragment = location.hash.startsWith('#token=') ? location.hash.slice(7) : null;
if (fragment) { sessionStorage.setItem('ppt-manager-token', decodeURIComponent(fragment)); history.replaceState(null,'','#/overview'); }
export async function api(op, body, query={}, options={}) {
  const qs=new URLSearchParams(query); const res=await fetch(`/api/${op}${qs.size?'?'+qs:''}`,{
    method:body===undefined?'GET':'POST', signal:options.signal, headers:{'Authorization':'Bearer '+(sessionStorage.getItem('ppt-manager-token')||''),...(body===undefined?{}:{'Content-Type':'application/json'})},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await res.json();if(!res.ok||data.ok===false)throw new Error(data.error||`HTTP ${res.status}`);return data.result;
}
export async function upload(file){
  if(!file||file.size>32*1024*1024)throw new Error('请选择不超过32MB的ZIP工具包');
  const r=await fetch('/api/package.inspect',{method:'POST',headers:{'Authorization':'Bearer '+sessionStorage.getItem('ppt-manager-token'),'Content-Type':'application/octet-stream'},body:file});
  const d=await r.json();if(!r.ok)throw new Error(d.error);return d.result;
}
export async function download(file){
  const r=await fetch('/api/file?id='+encodeURIComponent(file.file_id),{headers:{Authorization:'Bearer '+sessionStorage.getItem('ppt-manager-token')}});
  if(!r.ok)throw new Error('导出文件下载失败');
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=file.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
}
export async function copy(value){
  try{await navigator.clipboard.writeText(value);}catch{const t=document.createElement('textarea');t.value=value;document.body.append(t);t.select();document.execCommand('copy');t.remove();}
}
