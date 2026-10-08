import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../toolbox_manager/web/project-flow.js',import.meta.url),'utf8');
const {projectGraph,layoutGraph}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const nodes=[{id:'plan',after:[]},{id:'text',after:['plan']},{id:'search',after:['plan']},{id:'draw',after:['search']},{id:'merge',after:['draw','text']}];

function clearRoutes(layout){
 for(const a of layout.nodes){
  assert.ok(a.x>=0&&a.y>=0&&a.x+a.width<=layout.width+.01&&a.y+a.height<=layout.height+.01,a.id+' bounds');
  for(const b of layout.nodes){if(a.id===b.id)continue;assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,a.id+' overlaps '+b.id);}
 }
 for(const edge of layout.edges)for(let i=1;i<edge.points.length;i++){
  const a=edge.points[i-1],b=edge.points[i];
  assert.ok(a.x===b.x||a.y===b.y,'orthogonal segments');
  for(const n of layout.nodes){
   const crosses=a.y===b.y?a.y>n.y&&a.y<n.y+n.height&&Math.max(a.x,b.x)>n.x+.01&&Math.min(a.x,b.x)<n.x+n.width-.01:
    a.x>n.x&&a.x<n.x+n.width&&Math.max(a.y,b.y)>n.y+.01&&Math.min(a.y,b.y)<n.y+n.height-.01;
   assert.ok(!crosses,edge.from+' -> '+edge.to+' crosses '+n.id);
  }
 }
}

test('horizontal split and join keep every dependency without card collisions',()=>{
 const layout=layoutGraph(nodes,1000);
 assert.equal(layout.nodes.length,5);assert.equal(layout.edges.length,5);
 clearRoutes(layout);
 const find=id=>layout.nodes.find(n=>n.id===id);
 assert.equal(find('text').x,find('search').x);
 assert.equal(find('draw').y,find('search').y);
 assert.ok(find('merge').x>find('draw').x&&find('merge').x>find('text').x);
 assert.ok(layout.height<300,'short branch uses compact height');
 assert.notEqual(find('text').route.tone,find('search').route.tone);
 assert.equal(find('search').route.tone,find('draw').route.tone);
 assert.equal(find('merge').route.id,'main');
});
test('long sequences wrap left to right while keeping readable card sizes',()=>{
 const sequence=Array.from({length:18},(_,i)=>({id:'n'+i,after:i?['n'+(i-1)]:[]}));
 for(const available of [480,720,1100]){
  const layout=layoutGraph(sequence,available);clearRoutes(layout);
  assert.ok(layout.width<=available+.01);assert.ok(layout.bands>1);
  for(const n of layout.nodes)assert.ok(n.width>=152&&n.height>=80);
  for(const edge of layout.edges){
   const a=layout.nodes.find(n=>n.id===edge.from),b=layout.nodes.find(n=>n.id===edge.to);
   assert.ok(a.band<b.band||a.x<b.x);
   const last=edge.points.at(-1),previous=edge.points.at(-2);assert.ok(last.x>previous.x,'arrow enters next card from the left');
  }
 }
});
test('wide forks pack into groups instead of one tall column',()=>{
 const branches=Array.from({length:12},(_,i)=>({id:'b'+i,after:['root']}));
 const layout=layoutGraph([{id:'root',after:[]},...branches,{id:'join',after:branches.map(n=>n.id)}],1100);
 clearRoutes(layout);assert.equal(layout.edges.length,24);assert.ok(layout.bands>=2);assert.ok(layout.height<700);
 for(const node of layout.nodes)assert.ok(layout.nodes.filter(n=>n.band===node.band&&n.column===node.column).length<=3);
});
test('state-only updates preserve placement and route colors',()=>{
 const before=layoutGraph(nodes,720),after=layoutGraph(nodes.map(n=>({...n,status:'done'})),720);
 assert.deepEqual(before.nodes.map(n=>[n.id,n.x,n.y,n.route]),after.nodes.map(n=>[n.id,n.x,n.y,n.route]));
 assert.deepEqual(before.edges,after.edges);
});
test('replanned paths retain old nodes and use dashed connectors',()=>{
 const layout=layoutGraph([...nodes.map(n=>n.id==='draw'?{...n,status:'replaced'}:n),{id:'alternate',after:['search'],status:'running'}],720);
 clearRoutes(layout);assert.equal(layout.nodes.length,6);
 assert.ok(layout.edges.filter(e=>e.to==='draw'||e.from==='draw').every(e=>e.muted));
 assert.ok(layout.edges.some(e=>e.to==='alternate'&&!e.muted));
});
test('bounded mixed dependencies remain inside the canvas at desktop widths',()=>{
 const mixed=Array.from({length:64},(_,i)=>({id:'n'+i,after:i?[...new Set([i-1,Math.max(0,i-4),Math.max(0,i-7)])].map(j=>'n'+j):[]}));
 for(const width of [720,1100,1440]){
  const layout=layoutGraph(mixed,width);clearRoutes(layout);assert.equal(layout.edges.length,mixed.reduce((n,x)=>n+x.after.length,0));
 }
 assert.throws(()=>layoutGraph([...mixed,{id:'extra',after:[]}]),/上限/);
 assert.deepEqual(layoutGraph([]).edges,[]);
});
test('layout rejects cycles and missing nodes without hanging',()=>{
 assert.throws(()=>layoutGraph([{id:'a',after:['b']},{id:'b',after:['a']}]),/循环/);
 assert.throws(()=>layoutGraph([{id:'a',after:['missing']}]),/连接/);
});
test('default graph uses stage evidence and never marks a waiting project done',()=>{
 assert.equal(projectGraph({}).filter(n=>n.status==='planned').length,5);
 const graph=projectGraph({phase:{stage:'production'},checkpoints:[{event:'transition',from_stage:'plan'}]});
 assert.equal(graph.find(n=>n.id==='plan').status,'done');
 assert.equal(graph.find(n=>n.id==='intake').status,'planned');
});
test('observed tool failure updates view only and success is not step completion',()=>{
 const state={work_graph:{nodes:[{id:'draw',title:'Draw',after:[],status:'running',source:'agent',tools:['native.draw']} ]},activity:{calls:[{tool:'native.draw',status:'failed'}]}};
 assert.equal(projectGraph(state)[0].status,'failed');
 assert.equal(state.work_graph.nodes[0].status,'running');
 state.activity.calls[0].status='completed';assert.equal(projectGraph(state)[0].status,'running');
 state.activity.calls[0].status='running';assert.equal(projectGraph(state)[0].evidence,'工具正在执行');
});
test('graph does not attribute unbound tool calls to a custom step',()=>{
 const graph=projectGraph({work_graph:{nodes:[{id:'draw',status:'planned',after:[]}]},activity:{calls:[{tool:'unrelated',status:'running'}]}});
 assert.equal(graph[0].status,'planned');
});
