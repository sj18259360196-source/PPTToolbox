import {api} from './api.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={title:'标题',trigger:'适用条件',actions:'具体方法',verification:'验证方法',constraints:'限制与边界',tags:'标签',category:'分类'};
const arrays=new Set(['actions','verification','constraints','tags']);
function dialog(main,title){
 const d=document.createElement('dialog');d.className='learning-dialog source-experience-dialog';
 d.innerHTML=`<div class="learning-dialog-head"><h2>${esc(title)}</h2><button data-close>关闭</button></div><div data-body></div><p data-error role="alert"></p>`;
 main.append(d);d.onclose=()=>d.remove();d.querySelector('[data-close]').onclick=()=>d.close();d.showModal();return d;
}
function run(d,fn){return async()=>{const buttons=[...d.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await fn();}catch(e){d.querySelector('[data-error]').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=false);}};}
function fields(row){return Object.entries(labels).map(([k,label])=>`<label style="display:block;margin:12px 0">${label}${arrays.has(k)?'（每行一项）':''}<textarea data-field="${k}" rows="${arrays.has(k)?4:2}" style="display:block;width:100%;box-sizing:border-box">${esc(arrays.has(k)?(row[k]||[]).join('\n'):row[k])}</textarea></label>`).join('');}
export async function editExperience(main,id,reload){
 const data=await api('experience.edit-view',undefined,{id}),d=dialog(main,`编辑 ${id}`);
 d.querySelector('[data-body]').innerHTML=`<p>可调整方法和适用条件，原文出处会保留。保存后 Agent 检索会使用修改后的内容。</p>${fields(data.row)}<button data-save>保存修改</button>`;
 d.querySelector('[data-save]').onclick=run(d,async()=>{const changes={};d.querySelectorAll('[data-field]').forEach(e=>changes[e.dataset.field]=arrays.has(e.dataset.field)?e.value.split('\n').map(x=>x.trim()).filter(Boolean):e.value.trim());await api('experience.edit',{id,revision:data.revision,changes});d.close();await reload();});
}
export function mountManagement(main,reload,getIds){
 const actions=main.querySelector('.page-head .actions');
 actions.insertAdjacentHTML('afterbegin','<button data-import>导入</button><button data-export>导出当前结果</button><button data-dedup>检查重复</button><button data-history>版本记录</button><input data-import-file type="file" accept=".json,application/json" hidden>');
 const report=e=>main.querySelector('#experience-error').textContent=e.message;
 actions.querySelector('[data-export]').onclick=async()=>{try{const ids=getIds();if(!ids.length)throw Error('当前没有可导出的经验');const data=await api('experience.export',{ids});const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`经验库-${new Date().toISOString().slice(0,10)}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}catch(e){report(e);}};
 const input=actions.querySelector('[data-import-file]');actions.querySelector('[data-import]').onclick=()=>input.click();
 input.onchange=async()=>{try{const file=input.files[0];if(!file)return;if(file.size>24000000)throw Error('经验文件超过 24 MB');const payload=JSON.parse(await file.text()),preview=await api('experience.import-preview',{payload}),d=dialog(main,'导入预览');
 d.querySelector('[data-body]').innerHTML=`<p>新增 ${preview.new_count} 条，跳过 ${preview.duplicate_count} 条完全重复经验，补充 ${preview.evidence_update_count} 条出处。</p><ul>${preview.items.map(r=>`<li>${esc(r.title)}</li>`).join('')}</ul><p>编号冲突会自动分配新编号。内容相近的经验会保留，可在导入后检查重复。</p><button data-confirm>确认导入</button>`;
 d.querySelector('[data-confirm]').onclick=run(d,async()=>{await api('experience.import',{payload,revision:preview.revision});d.close();await reload();});}catch(e){report(e);}finally{input.value='';}};
 actions.querySelector('[data-dedup]').onclick=async()=>{try{const data=await api('experience.duplicates'),d=dialog(main,'检查重复');
 d.querySelector('[data-body]').innerHTML=`<p>发现 ${data.total} 组候选，最多显示 200 组。相近条目需要查看方法后再决定。合并保留双方的方法和出处。</p>${data.pairs.map((p,i)=>`<article class="learning-row"><p>${esc(p.left)} · ${esc(p.left_title)}<br>${esc(p.right)} · ${esc(p.right_title)}</p><p>${p.exact?'方法字段完全相同':'标题和适用条件相近'}</p><button data-compare="${i}">查看并选择合并</button></article>`).join('')||'<p>没有发现重复候选。</p>'}`;
 d.onclick=async e=>{const b=e.target.closest('[data-compare]');if(!b)return;try{const p=data.pairs[+b.dataset.compare],left=await api('experience.edit-view',undefined,{id:p.left}),right=await api('experience.edit-view',undefined,{id:p.right});if(left.revision!==data.revision||right.revision!==data.revision)throw Error('经验库已更新，请重新检查重复');const compare=dialog(main,'合并前核对');compare.querySelector('[data-body]').innerHTML=`${[left.row,right.row].map(r=>`<h3>${esc(r.id)} · ${esc(r.title)}</h3>${Object.entries(labels).filter(([k])=>k!=='title').map(([k,l])=>`<p><strong>${l}</strong></p><pre style="white-space:pre-wrap">${esc(arrays.has(k)?r[k].join('\n'):r[k])}</pre>`).join('')}`).join('')}<label>保留编号 <select data-keep><option value="${esc(p.left)}">${esc(p.left)}</option><option value="${esc(p.right)}">${esc(p.right)}</option></select></label> <button data-merge>确认合并并保留历史</button>`;compare.querySelector('[data-merge]').onclick=run(compare,async()=>{const keep=compare.querySelector('[data-keep]').value;await api('experience.merge',{keep,remove:keep===p.left?p.right:p.left,revision:data.revision});compare.close();d.close();await reload();});}catch(err){d.querySelector('[data-error]').textContent=err.message;}};
 }catch(e){report(e);}};
 actions.querySelector('[data-history]').onclick=async()=>{try{const data=await api('experience.history'),d=dialog(main,'版本记录');d.querySelector('[data-body]').innerHTML=`<p>显示最近 50 次修改。撤销会恢复最近一次修改前的经验库。</p>${data.items.length?'<button data-undo>撤销最近一次修改</button>':''}<ul>${data.items.map(r=>`<li>${esc(new Date(r.at).toLocaleString())} · ${esc(r.summary)}</li>`).join('')}</ul>${data.items.length?'':'<p>还没有修改记录。</p>'}`;const undo=d.querySelector('[data-undo]');if(undo)undo.onclick=run(d,async()=>{await api('experience.undo',{history_id:data.items[0].id,revision:data.revision});d.close();await reload();});}catch(e){report(e);}};
}
