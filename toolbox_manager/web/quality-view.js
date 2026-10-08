const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function qualitySummary(page){
 const objects=(page?.objects||[]).filter(o=>o.scene.kind!=='group');
 const raster=objects.filter(o=>o.scene.kind==='image');
 const flagged=raster.filter(o=>['icon','logo'].includes(o.scene.asset_role)||!o.scene.raster_content||!o.scene.raster_reason);
 const gradients=objects.filter(o=>o.scene.style?.gradient||o.scene.style?.line_gradient);
 const alpha=objects.filter(o=>{const s=o.scene.style||{};return (s.fill_alpha??1)<1||(s.line_alpha??1)<1||[...(s.gradient?.stops||[]),...(s.line_gradient?.stops||[])].some(x=>(x.alpha??1)<1)});
 return {native:objects.length-raster.length,raster,flagged,gradients:gradients.length,alpha:alpha.length,
  observed:objects.filter(o=>o.pptx!=null).length,office:page?.images?.candidate?.status==='available'};
}
export function qualityMarkup(page){
 const q=qualitySummary(page);
 return `<section class="wb-quality" aria-label="当前页质量检查"><div class="wb-quality-metrics"><div><span>原生对象</span><strong>${q.native}</strong></div><div><span>位图</span><strong>${q.raster.length}</strong></div><div><span>渐变 / 透明</span><strong>${q.gradients} / ${q.alpha}</strong></div><div><span>PowerPoint 预览</span><strong class="wb-quality-label">${q.office?'可查看':'待生成'}</strong></div></div><p class="wb-quality-caption">对象数量来自当前场景，已从 PPTX 读到 ${q.observed} 个对象。请结合原图检查轮廓、文字和编辑效果。</p>${q.raster.length?`<details class="wb-raster-review"><summary>${q.flagged.length?`${q.flagged.length} 个位图需要核对重绘方式`:'查看保留位图的依据'}</summary><div>${q.raster.map(o=>`<button type="button" data-object="${escape(o.id)}"><span>${escape(o.id.split('.').at(-1))}</span><small>${escape(['icon','logo'].includes(o.scene.asset_role)?'图标或标志需要原生重绘':o.scene.raster_reason||'尚未记录保留位图的依据')}</small></button>`).join('')}</div></details>`:''}</section>`;
}
