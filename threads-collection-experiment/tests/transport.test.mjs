// Every HTTP transport in this file is an in-memory mock. No platform requests.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
import {boundedTransport,runQuery} from '../scripts/bounded_search.mjs';
const root=path.resolve(import.meta.dirname,'..');
const cfg=JSON.parse(await fs.readFile(path.join(root,'config/experiment.json'),'utf8'));
const body=JSON.parse(await fs.readFile(path.join(root,'../threads-part2/run_20261031_210039/quanlian_core.json'),'utf8'));

test('serialized transport cannot exceed actual HTTP budget',async()=>{
  let active=0,peak=0,calls=0;
  const t=boundedTransport({maxRequests:2,minimumIntervalMs:0,timeoutMs:1000,maxBytes:5000,fetchImpl:async()=>{
    calls++;active++;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,5));active--;return new Response('<html>ok</html>');}});
  const results=await Promise.allSettled([1,2,3,4].map(n=>t.fetchFn(`https://www.threads.com/search?q=fixture${n}`)));
  assert.equal(calls,2);assert.equal(peak,1);assert.equal(t.state.httpRequestCount,2);
  assert.equal(t.state.fatal.code,'REQUEST_BUDGET');assert.equal(results.filter(r=>r.status==='fulfilled').length,2);
});

test('429 aborts queued requests; collector retries cannot cause another real request',async()=>{
  let calls=0;const t=boundedTransport({maxRequests:8,minimumIntervalMs:0,timeoutMs:1000,maxBytes:5000,fetchImpl:async()=>{calls++;return new Response('rate limited',{status:429});}});
  await Promise.allSettled([t.fetchFn('https://www.threads.com/search'),t.fetchFn('https://www.threads.net/search')]);
  await assert.rejects(t.fetchFn('https://www.threads.com/search'),{name:'AbortError'});
  assert.equal(calls,1);assert.equal(t.state.fatal.code,'RATE_LIMIT');
});

test('challenge and foreign redirects stop without follow-up',async()=>{
  const challenge=boundedTransport({maxRequests:3,minimumIntervalMs:0,timeoutMs:1000,maxBytes:5000,fetchImpl:async()=>new Response('<title>Log in</title>')});
  await assert.rejects(challenge.fetchFn('https://www.threads.com/search'),{name:'AbortError'});
  assert.equal(challenge.state.fatal.code,'ACCESS_CHALLENGE');
  let n=0;const redirect=boundedTransport({maxRequests:3,minimumIntervalMs:0,timeoutMs:1000,maxBytes:5000,fetchImpl:async()=>{n++;return new Response('',{status:302,headers:{location:'https://unapproved.example/login'}});}});
  await assert.rejects(redirect.fetchFn('https://www.threads.com/search'));
  assert.equal(n,1);assert.equal(redirect.state.fatal.code,'UNAPPROVED_REDIRECT');
});

test('cookie and authorization are not forwarded',async()=>{
  let received;const t=boundedTransport({maxRequests:1,minimumIntervalMs:0,timeoutMs:1000,maxBytes:5000,fetchImpl:async(u,init)=>{received=init;return new Response('ok');}});
  await t.fetchFn('https://www.threads.com/search',{headers:{Cookie:'fixture',Authorization:'fixture'},dispatcher:'fixture'});
  assert.ok(!Object.keys(received.headers).some(k=>/cookie|authorization/i.test(k)));
  assert.equal(received.dispatcher,undefined);assert.equal(received.redirect,'manual');
});

test('wrapper refuses unapproved collection before importing collector',async()=>{
  let calls=0;const r=await runQuery(cfg,{stage:'A',keyword:'全聯',limit:20,max_http_requests:6},{fetchImpl:async()=>{calls++;return new Response('');}});
  assert.equal(r.status,'BLOCKED_AUTHORIZATION');assert.equal(calls,0);
});

test('real pinned SDK errors swallowed upstream still become FAILED in wrapper',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'threads-mock-'));
  const evidence=path.join(dir,'test_evidence.txt');await fs.writeFile(evidence,'UNIT TEST ONLY - no platform authorization');
  const c=structuredClone(cfg);c.authorization={status:'approved',approved_methods:['ckelepel-public-http'],evidence_file:evidence,valid_until_utc:'2099-01-01T00:00:00Z'};
  c.stopping.minimum_http_interval_seconds=0;
  let calls=0;const r=await runQuery(c,{stage:'A',keyword:'全聯',limit:20,max_http_requests:6,raw_dir:path.join(dir,'http'),result_path:path.join(dir,'result.json'),metadata_path:path.join(dir,'manifest.json')},
    {fetchImpl:async()=>{calls++;return new Response('rate limited',{status:429});}});
  assert.equal(calls,1);assert.equal(r.status,'FAILED');assert.equal(r.exit_code,1);assert.equal(r.error.code,'RATE_LIMIT');
});

test('pinned SDK extracts a real fixture and records matching receipt time without live calls',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'threads-mock-'));
  const evidence=path.join(dir,'test_evidence.txt');await fs.writeFile(evidence,'UNIT TEST ONLY');
  const c=structuredClone(cfg);c.authorization={status:'approved',approved_methods:['ckelepel-public-http'],evidence_file:evidence,valid_until_utc:'2099-01-01T00:00:00Z'};
  c.stopping.minimum_http_interval_seconds=0;
  const p=body.results[1];
  const post={pk:p.id,code:p.code,caption:{text:p.caption},taken_at:p.taken_at,user:p.user,like_count:p.like_count,reply_count:p.reply_count,text_post_app_info:{repost_count:p.repost_count,quote_count:p.quote_count}};
  const html='<html><script type="application/json">'+JSON.stringify({searchResults:{edges:[{node:{thread_items:[{post}]}}]}})+'</script></html>';
  let calls=0;const r=await runQuery(c,{stage:'A',keyword:'全聯',limit:1,max_http_requests:6,raw_dir:path.join(dir,'http'),result_path:path.join(dir,'result.json'),metadata_path:path.join(dir,'manifest.json')},
    {fetchImpl:async()=>{calls++;return new Response(html);}});
  assert.equal(r.status,'SUCCESS');assert.ok(calls>=1 && calls<=2);assert.ok(r.result_observations[0].response_received_at);
  assert.equal(r.simulation,true);assert.equal(r.network_executed,false);
  const result=JSON.parse(await fs.readFile(path.join(dir,'result.json'),'utf8'));
  assert.equal(result.results[0].id,p.id);assert.equal(result.results[0].caption,p.caption);
});
