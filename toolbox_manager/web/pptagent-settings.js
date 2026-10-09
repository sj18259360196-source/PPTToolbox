import {renderAgentMetrics} from './pptagent-visibility.js';
import {api} from './api.js';
import {projectIndex} from './project-index.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states={queued:'等待处理',running:'正在处理',completed:'处理结束',failed:'处理失败',cancelled:'已取消',interrupted:'已中断'};
export async function mountPPTAgent(main){
 main.querySelector('#pptagent-settings')?.remove();
 const host=document.createElement('section');host.id='pptagent-settings';main.append(host);
 let timer,loading=false;
 try{
  let cfg=await api('pptagent.settings');if(!host.isConnected)return;
  const stateText=()=>!cfg.endpoint||!cfg.model?'尚未配置':cfg.connection?.status==='ready'?(cfg.connection.tools_verified?'连接与工具调用已验证':'最近调用成功'):cfg.connection?.status==='unavailable'?'最近调用失败，本地记录继续更新':'配置已保存 · 连接尚未验证';
  host.innerHTML=`<section id="pptagent-usage" class="panel panel-body agent-usage-panel"><p class="muted">正在读取用量…</p></section><div class="pptagent-layout"><section class="panel panel-body"><h2>驻留 PPTAgent</h2><p class="muted">通过 Responses API 整理项目记录、查询经验、处理申请、整理工作图和保存管理备注。</p><div class="api-connection-status" id="api-connection-state">${esc(stateText())}</div><form class="pptagent-form" id="pptagent-config"><label>完整 API 地址<input name="endpoint" type="url" value="${esc(cfg.endpoint)}" placeholder="https://服务地址/v1/responses" autocomplete="off"></label><label>模型名称<input name="model" value="${esc(cfg.model)}" maxlength="150" placeholder="填写服务商提供的模型名称" autocomplete="off"></label><label>API Key<input name="api_key" type="password" autocomplete="new-password" placeholder="${cfg.key_saved?'已加密保存，留空保留':'填写 API Key，本机免密服务可留空'}"></label><label class="inline-label"><input type="checkbox" name="enabled" ${cfg.enabled?'checked':''}>启用 PPTAgent</label><details><summary>兼容设置</summary><label>接口协议<select name="protocol"><option value="responses">Responses API</option><option value="chat">Chat Completions，仅辅助摘要</option></select></label><label class="inline-label"><input type="checkbox" name="clear_key">清除已保存的 Key</label></details><p class="small muted">Key 加密保存在本机。保存后可测试连接，测试包含一次工具调用，不读取项目内容。</p><div class="pptagent-actions"><button class="primary" type="submit">保存设置</button><button type="button" id="pptagent-test">测试连接</button></div><p role="status"></p></form></section><section class="panel panel-body"><h2>管理助手</h2><p class="muted">查询项目和经验，按已有授权规则处理申请，或给所选项目更新工作图与管理备注。</p><form class="pptagent-form" id="pptagent-task"><label>项目范围<select name="project"><option value="">全部项目，只查询与处理申请</option></select></label><label>交给 PPTAgent<textarea name="prompt" rows="4" maxlength="2000" required placeholder="查看待办申请，按已有授权规则处理，并说明仍需我决定的事项。"></textarea></label><div class="pptagent-actions"><button class="primary" type="submit">开始处理</button><button type="button" id="pptagent-requests">填入待办任务</button></div><p role="status"></p></form><details class="pptagent-tools"><summary>可用功能与范围</summary><p class="small muted">查询项目 · 读取项目记录 · 检索经验 · 查询待办 · 按已有规则审批 · 保存管理备注 · 更新工作图</p><p class="small muted">工作图与管理备注单独保存，制作 Agent 负责 PPT 和阶段打卡。批量交付、归档与排序在项目页直接操作。</p><p class="small muted">每次最多 4 轮请求、8 次工具调用，失败后不会自动重复执行。</p></details></section></div><section class="panel panel-body pptagent-history"><div class="chain-section-head"><h2>最近处理</h2><button id="pptagent-refresh">刷新记录</button></div><div id="pptagent-tasks" aria-live="polite"></div></section>`;
  const configForm=host.querySelector('#pptagent-config'),taskForm=host.querySelector('#pptagent-task');
  configForm.querySelector('details').insertAdjacentHTML('beforebegin',`<label>近 1 小时请求上限<input name="hourly_request_limit" type="number" min="1" max="10000" step="1" required value="${esc(cfg.hourly_request_limit)}"></label><label>近 24 小时请求上限<input name="daily_request_limit" type="number" min="1" max="10000" step="1" required value="${esc(cfg.daily_request_limit)}"></label><label>同项目自动整理间隔（秒）<input name="summary_interval_seconds" type="number" min="60" max="86400" step="1" required value="${esc(cfg.summary_interval_seconds)}"></label><p class="small muted">请求上限涵盖自动整理、管理任务和连接测试，失败尝试也计数。重启或修改配置不清零。每批集中更新工作图、摘要与备注，无新增信息不请求。当前自动补图使用 Responses 协议。本地记录与 PPT 制作不受影响。</p>`);
  configForm.elements.protocol.value=cfg.protocol;
  const selected=new URLSearchParams(location.hash.split('?')[1]||'').get('project');
  projectIndex().then(index=>{
   if(!host.isConnected)return;
   for(const row of index.rows.filter(r=>!r.archived)){
    const option=document.createElement('option');option.value=row.id;option.textContent=row.label;
    option.selected=row.id===selected;taskForm.elements.project.append(option);
   }
  }).catch(error=>{taskForm.querySelector('[role=status]').textContent=error.message;});
  const values=()=>({revision:cfg.revision,enabled:configForm.elements.enabled.checked,protocol:configForm.elements.protocol.value,
   endpoint:configForm.elements.endpoint.value.trim().replace(/\/$/,''),model:configForm.elements.model.value.trim(),
   api_key:configForm.elements.api_key.value,clear_key:configForm.elements.clear_key.checked,
   hourly_request_limit:Number(configForm.elements.hourly_request_limit.value),
   daily_request_limit:Number(configForm.elements.daily_request_limit.value),
   summary_interval_seconds:Number(configForm.elements.summary_interval_seconds.value)});
  const saved=()=>{const v=values();return !v.api_key&&!v.clear_key&&['enabled','protocol','endpoint','model','hourly_request_limit','daily_request_limit','summary_interval_seconds'].every(k=>v[k]===cfg[k]);};
  configForm.onsubmit=async e=>{
   e.preventDefault();const button=configForm.querySelector('[type=submit]');button.disabled=true;
   try{
    cfg=await api('pptagent.settings.save',values());
    configForm.elements.api_key.value='';configForm.elements.api_key.placeholder=cfg.key_saved?'已加密保存，留空保留':'填写 API Key，本机免密服务可留空';configForm.elements.clear_key.checked=false;
    host.querySelector('#api-connection-state').textContent=stateText();
    configForm.querySelector('[role=status]').textContent=cfg.enabled?'已保存并启用。可测试连接或发起管理任务。':'配置已保存，PPTAgent 尚未启用。';
   }catch(error){configForm.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}
  };
  host.querySelector('#pptagent-test').onclick=async e=>{
   if(!saved()){configForm.querySelector('[role=status]').textContent='配置有改动，请先保存设置。';return;}
   e.target.disabled=true;
   try{await api('pptagent.test',{id:crypto.randomUUID(),revision:cfg.revision});configForm.querySelector('[role=status]').textContent='正在后台测试，结果会显示在下方。';await refresh();}
   catch(error){configForm.querySelector('[role=status]').textContent=error.message;}finally{e.target.disabled=false;}
  };
  host.querySelector('#pptagent-requests').onclick=()=>{taskForm.elements.prompt.value='查看待办申请，按已有授权规则处理，并说明仍需我决定的事项。';taskForm.elements.prompt.focus();};
  taskForm.onsubmit=async e=>{
   e.preventDefault();const button=taskForm.querySelector('[type=submit]');button.disabled=true;
   if(!saved()){taskForm.querySelector('[role=status]').textContent='接入配置有改动，请先保存设置。';button.disabled=false;return;}
   try{
    await api('pptagent.run',{id:crypto.randomUUID(),revision:cfg.revision,prompt:taskForm.elements.prompt.value,project:taskForm.elements.project.value||null});
    taskForm.querySelector('[role=status]').textContent='任务已登记，进度和工具调用显示在下方。';await refresh();
   }catch(error){taskForm.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}
  };
  host.querySelector('#pptagent-tasks').onclick=async e=>{
   const button=e.target.closest('[data-cancel-task]');if(!button)return;button.disabled=true;
   try{await api('pptagent.cancel',{id:button.dataset.cancelTask});await refresh();}
   catch(error){taskForm.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}
  };
  async function refresh(){
   clearTimeout(timer);if(!host.isConnected)return;if(loading){timer=setTimeout(refresh,250);return;}loading=true;
   try{
    const [rows,metrics]=await Promise.all([api('pptagent.tasks'),api('pptagent.metrics')]);if(!host.isConnected)return;
    const usagePanel=host.querySelector('#pptagent-usage'),expanded=usagePanel.querySelector('details')?.open;usagePanel.innerHTML=renderAgentMetrics(metrics);if(expanded)usagePanel.querySelector('details').open=true;
    host.querySelector('#pptagent-tasks').innerHTML=rows.length?rows.slice(0,8).map(row=>`<article class="pptagent-record"><div class="chain-section-head"><strong>${esc(row.kind==='probe'?'连接与工具测试':row.prompt)}</strong><span>${esc(states[row.status]||row.status)}</span>${['queued','running'].includes(row.status)?`<button data-cancel-task="${esc(row.id)}">取消</button>`:''}</div><p class="small muted">${esc(new Date(row.created_at).toLocaleString())} · ${metrics.task_usage?.[row.id]?.reported?Number(metrics.task_usage[row.id].total_tokens).toLocaleString()+' Token':'用量未记录'}</p>${row.steps.map(step=>`<div class="pptagent-step ${step.status==='failed'?'chain-warning':''}"><span>${esc(step.label)}</span><span>${esc(step.status==='running'?'执行中':step.status==='failed'?'未完成':'已返回')}</span>${step.result?.error?`<p>${esc(step.result.error)}</p>`:''}</div>`).join('')}${row.result?`<p class="pptagent-result">${esc(row.result)}</p>`:''}</article>`).join(''):'<p class="muted">尚无处理记录。保存配置后，可先测试连接。</p>';
    const latest=await api('pptagent.settings');if(!host.isConnected)return;
    if(latest.revision===cfg.revision)cfg=latest;
    else configForm.querySelector('[role=status]').textContent='接入配置已在其他窗口更改，请重新打开此页。';
    host.querySelector('#api-connection-state').textContent=stateText();
    const probe=rows.find(r=>r.kind==='probe');
    if(probe&&!['queued','running'].includes(probe.status)&&configForm.querySelector('[role=status]').textContent.startsWith('正在后台测试'))configForm.querySelector('[role=status]').textContent=probe.result;
    timer=setTimeout(refresh,rows.some(r=>['queued','running'].includes(r.status))||metrics.active?1000:5000);
   }catch(error){if(host.isConnected)taskForm.querySelector('[role=status]').textContent=error.message;}finally{loading=false;}
  }
  host.querySelector('#pptagent-refresh').onclick=refresh;await refresh();
 }catch(error){if(host.isConnected)host.textContent=error.message;}
}
