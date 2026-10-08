export function createImageViewer(host){
 let serial=0,active=null,disposed=false;
 const close=()=>{serial++;active?.close();};
 return {
  close,
  async open(title,load){
   close();const request=serial,blob=await load();if(disposed||request!==serial||!host.isConnected)return;
   const url=URL.createObjectURL(blob),dialog=document.createElement('dialog');active=dialog;
   dialog.className='project-image-viewer';dialog.setAttribute('aria-label',title);
   dialog.innerHTML='<header><strong></strong><div class="actions"><button data-zoom="out" aria-label="缩小图片">−</button><button data-zoom="fit">适应窗口</button><button data-zoom="in" aria-label="放大图片">＋</button><button data-close>关闭预览</button></div></header><div class="image-viewer-scroll"><img></div>';
   dialog.querySelector('strong').textContent=title;const img=dialog.querySelector('img');img.alt=title;img.src=url;
   let zoom=1;const draw=()=>{dialog.dataset.zoomed=String(zoom>1);img.style.width=zoom>1?`${zoom*100}%`:'';img.style.maxWidth=zoom>1?'none':'';img.style.maxHeight=zoom>1?'none':'';};
   dialog.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{zoom=b.dataset.zoom==='fit'?1:Math.max(1,Math.min(4,zoom+(b.dataset.zoom==='in'?.5:-.5)));draw();});
   dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.onclose=()=>{URL.revokeObjectURL(url);dialog.remove();if(active===dialog)active=null;};
   host.append(dialog);dialog.showModal();dialog.querySelector('[data-close]').focus();
  },
  dispose(){disposed=true;close();}
 };
}
