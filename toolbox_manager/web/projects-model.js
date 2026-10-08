export const requestLabels = {awaiting_authorization:'待授权',approved:'等待 Agent 启动',rejected:'已拒绝',started:'等待项目登记'};
const states = {registered:'已登记',folder:'项目文件夹',delivered:'已交付',awaiting_visual_review:'待视觉验收',running:'制作中',in_progress:'制作中',completed:'已完成',failed:'失败',draft:'草稿',paused:'已暂停',ready:'待开始',awaiting_agent:'等待 Agent',awaiting_revision:'待修改',blocked:'受阻'};
export const categoryLabel = value => ({folder:'文件夹项目',agent:'Agent 项目',historical:'历史项目',manual:'手动项目'}[value] || value || '未分类');
export const stateLabel = value => states[value] || value || '待更新';
const pathKey = value => String(value || '').replaceAll('\\','/').replace(/\/+$/,'').toLowerCase();
export function linkedRequests(project, requests) {
  return requests.filter(request => request.project_id
    ? [project.id,project.project_id].includes(request.project_id)
    : pathKey(request.path) && pathKey(request.path) === pathKey(project.work_directory || project.path));
}
export function projectItems(projects, requests, order=[]) {
  const positions=new Map(order.map((key,index)=>[key,index]));
  const linked = new Set(projects.flatMap(project => linkedRequests(project,requests).map(r=>r.id)));
  return [
    ...projects.map(project=>({key:project.id,project,requests:linkedRequests(project,requests),label:project.label,path:project.work_directory||project.path||'',category:project.category||'historical',archived:!!project.archived})),
    ...requests.filter(request=>!linked.has(request.id)).map(request=>({key:`request:${request.id}`,project:null,requests:[request],label:request.label,path:request.path,category:'agent',archived:!!request.archived}))
  ].map(item=>({...item,position:positions.get(item.key)??Number.MAX_SAFE_INTEGER}));
}
export function filterItems(items,{view='active',query='',category='',onlyDelivery=false,sort='updated'}={}) {
  const search=query.trim().toLowerCase();
  const filtered=items.filter(item=>item.archived===(view==='archived')
    && (view==='pending' ? item.requests.some(r=>r.status==='awaiting_authorization'&&!r.archived) : view==='deliveries'?(item.project?.has_delivery||item.project?.storage?.deliveries?.length>0):view==='completed' ? item.project?.lifecycle?.status==='completed' : true)
    && (!category||item.category===category)
    && (!onlyDelivery||item.project?.has_delivery||item.project?.storage?.deliveries?.length)
    && `${item.label} ${item.path} ${item.project?.project_id||''} ${item.project?.gallery?.search_text||''} ${(item.project?.storage?.deliveries||[]).map(f=>f.path).join(' ')}`.toLowerCase().includes(search));
  const updated=item=>Date.parse(item.project?.updated_at||item.requests.at(-1)?.updated_at)||0;
  return filtered.sort((a,b)=>sort==='manual'?a.position-b.position:sort==='size'?(b.project?.storage?.bytes??-1)-(a.project?.storage?.bytes??-1):sort==='name'?a.label.localeCompare(b.label,'zh-CN'):sort==='name-desc'?b.label.localeCompare(a.label,'zh-CN'):sort==='oldest'?updated(a)-updated(b):updated(b)-updated(a));
}
export function managementRow(item){
 return item.project||{...item.requests[0],id:item.key,request_id:item.requests[0].id,work_directory:item.path,archived:item.archived};
}
export function formatBytes(value){
  if(!Number.isFinite(value))return '待统计';
  if(value<1024)return `${value} B`;
  const units=['KiB','MiB','GiB','TiB'];let n=value/1024,i=0;
  while(n>=1024&&i<units.length-1){n/=1024;i++;}
  return `${n.toFixed(n>=100?0:1)} ${units[i]}`;
}
export function groupedItems(items,expanded=new Set(),flat=false){
  if(flat)return items.map(item=>({item,depth:0,children:0}));
  const keys=new Set(items.map(i=>i.key)),children=new Map();
  for(const item of items){const parent=item.project?.parent_id;if(parent&&keys.has(parent)&&parent!==item.key){if(!children.has(parent))children.set(parent,[]);children.get(parent).push(item);}}
  const result=[],seen=new Set();
  function add(item,depth){if(seen.has(item.key))return;seen.add(item.key);const nested=children.get(item.key)||[];result.push({item,depth,children:nested.length});if(expanded.has(item.key))for(const child of nested)add(child,depth+1);}
  items.filter(i=>!keys.has(i.project?.parent_id)||i.project?.parent_id===i.key).forEach(i=>add(i,0));
  return result;
}
export function suggestedParent(row,rows){
  const path=pathKey(row.work_directory);
  return rows.filter(r=>r.id!==row.id&&path.startsWith(pathKey(r.work_directory)+'/')).sort((a,b)=>b.work_directory.length-a.work_directory.length)[0];
}
export function projectFamily(rows,selected){
 const byId=new Map(rows.map(row=>[row.id,row]));let root=byId.get(selected);
 if(!root)return [];
 const ancestors=new Set([root.id]);
 while(byId.has(root.parent_id)&&!ancestors.has(root.parent_id)){root=byId.get(root.parent_id);ancestors.add(root.id);}
 const included=new Set([root.id]);
 for(let depth=0;depth<12;depth++){
  const children=rows.filter(row=>!included.has(row.id)&&included.has(row.parent_id));
  if(!children.length)break;children.forEach(row=>included.add(row.id));
 }
 return rows.filter(row=>included.has(row.id)).map(row=>row.id===root.id?{...row,parent_id:null}:row);
}
export function localTime(value) {
  const date=new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date) : '—';
}
