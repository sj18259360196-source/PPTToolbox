import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../toolbox_manager/web/projects-model.js',import.meta.url),'utf8');
const {projectItems,filterItems,localTime,stateLabel,formatBytes,groupedItems,suggestedParent,projectFamily,managementRow}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const project={id:'view-1',project_id:'pid-1',label:'Example',work_directory:'A:\\Work\\Demo',category:'agent'};
const request={id:'req-1',project_id:'pid-1',label:'Example',path:'A:\\Work\\Demo',status:'started'};

test('work chain shows its own project family and handles broken parent cycles',()=>{
 const rows=[{id:'a'},{id:'a1',parent_id:'a'},{id:'a2',parent_id:'a1'},{id:'b'},{id:'b1',parent_id:'b'}];
 assert.deepEqual(projectFamily(rows,'a1').map(r=>r.id),['a','a1','a2']);
 assert.deepEqual(projectFamily(rows,'missing'),[]);
 const cyclic=projectFamily([{id:'a',parent_id:'b'},{id:'b',parent_id:'a'}],'a');
 assert.equal(cyclic.filter(r=>!r.parent_id).length,1);
});
test('linked authorization appears within one project',()=>{
 const items=projectItems([project],[request]);
 assert.equal(items.length,1);assert.equal(items[0].requests.length,1);
});
test('unlinked requests stay visible and different explicit identities do not merge',()=>{
 assert.equal(projectItems([project],[{...request,project_id:'other'}]).length,2);
 assert.equal(projectItems([],[request]).length,1);
});
test('unregistered intents join batch selection with separate request identities',()=>{
 const items=projectItems([project],[{...request,project_id:'other',revision:7}]);
 const rows=items.map(managementRow);
 assert.equal(rows[0].id,project.id);
 assert.equal(rows[1].id,'request:req-1');assert.equal(rows[1].request_id,'req-1');assert.equal(rows[1].revision,7);
});
test('archived intents leave active and pending tabs and can be restored',()=>{
 const items=projectItems([],[{...request,status:'awaiting_authorization',archived:true}]);
 assert.equal(filterItems(items).length,0);assert.equal(filterItems(items,{view:'pending'}).length,0);
 assert.equal(filterItems(items,{view:'archived'}).length,1);
 assert.equal(managementRow(items[0]).archived,true);
 assert.equal(filterItems(projectItems([],[{...request,archived:false}])).length,1);
});
test('legacy requests match normalized full paths, never names',()=>{
 assert.equal(projectItems([project],[{...request,project_id:null,path:'a:/work/demo/'}]).length,1);
 assert.equal(projectItems([project],[{...request,project_id:null,path:'A:/Other/Demo'}]).length,2);
});
test('archived linked projects do not reappear as standalone requests',()=>{
 const items=projectItems([{...project,archived:true}],[request]);
 assert.equal(filterItems(items).length,0);
 assert.equal(filterItems(items,{view:'archived'}).length,1);
});
test('archived projects leave the pending view',()=>{
 const items=projectItems([{...project,archived:true}],[{...request,status:'awaiting_authorization'}]);
 assert.equal(filterItems(items,{view:'pending'}).length,0);
});
test('search includes path and category combines with query',()=>{
 const items=projectItems([project],[request]);
 assert.equal(filterItems(items,{query:'a:\\work',category:'agent'}).length,1);
 assert.equal(filterItems(items,{query:'pid-1'}).length,1);
 assert.equal(filterItems(items,{query:'Example',category:'manual'}).length,0);
});
test('timestamps and unknown statuses have safe fallbacks',()=>{
 assert.equal(localTime('invalid'),'—');
 assert.equal(stateLabel('delivered'),'已交付');
 assert.equal(stateLabel('future-status'),'future-status');
});
test('archived deliveries are visible only in the archive',()=>{
 const items=projectItems([{...project,archived:true,lifecycle:{status:'completed'},storage:{deliveries:[{path:'delivery/v1/editable.pptx'}]}}],[]);
 assert.equal(filterItems(items,{view:'deliveries'}).length,0);
 assert.equal(filterItems(items,{view:'completed'}).length,0);
 assert.equal(filterItems(items,{view:'archived'}).length,1);
});
test('manual order is shared by mixed rows and date sorting includes requests',()=>{
 const req={...request,id:'orphan',project_id:'other',updated_at:'2026-10-08T00:00:00Z'};
 const items=projectItems([{...project,updated_at:'2026-10-01T00:00:00Z'}],[req],['request:orphan',project.id]);
 assert.equal(filterItems(items,{sort:'manual'})[0].key,'request:orphan');
 assert.equal(filterItems(items,{sort:'updated'})[0].key,'request:orphan');
 assert.equal(filterItems(items,{sort:'oldest'})[0].key,project.id);
});
test('grouping is metadata only and searches can stay flat',()=>{
 const child={...project,id:'child',label:'Child',parent_id:project.id,work_directory:'A:\\Work\\Demo\\pages\\one'};
 const items=projectItems([project,child],[]);
 assert.equal(groupedItems(items).length,1);
 assert.equal(groupedItems(items,new Set([project.id]))[1].depth,1);
 assert.equal(groupedItems(items,new Set(),true).length,2);
 assert.equal(suggestedParent(child,[project,child]).id,project.id);
});
test('size sorting and unknown sizes remain truthful',()=>{
 const items=projectItems([project,{...project,id:'large',storage:{bytes:2048,deliveries:[]}}],[]);
 assert.equal(filterItems(items,{sort:'size'})[0].key,'large');
 assert.equal(formatBytes(undefined),'待统计');
 assert.equal(formatBytes(0),'0 B');
 assert.equal(formatBytes(1024**3),'1.0 GiB');
});
