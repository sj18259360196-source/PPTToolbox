import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../toolbox_manager/web/pptagent-visibility.js',import.meta.url),'utf8');
const {renderAgentBudget,renderAgentMetrics,renderProjectAssistance}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('request budget and recovery time visible globally and per project',()=>{
 const budget={last_hour:3,last_24_hours:9,hourly_request_limit:3,daily_request_limit:10,summary_interval_seconds:60,blocked:true,retry_at:1790000000};
 for(const html of [renderAgentBudget(budget),renderAgentMetrics({budget}),renderProjectAssistance({assistant:{status:'rate_limited',metrics:{budget}}},'p')]){
  assert.ok(html.includes('3 / 3')&&html.includes('9 / 10'));
  assert.ok(html.includes('最早恢复时间')&&html.includes('本地记录'));
 }
});
test('old metrics stay renderable and discarded summaries explain deduplication',()=>{
 assert.equal(renderAgentBudget(), '');
 assert.ok(renderAgentMetrics().includes('PPTAgent 用量'));
 assert.ok(renderAgentBudget({hourly_request_limit:3,summary_outcome:'discarded'}).includes('不重复请求旧内容'));
});
