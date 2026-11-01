// Guard the existing ckelepel SDK: serialize/count every HTTP request, disable retries,
// archive each response, and detect failures that the upstream SDK otherwise swallows.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';

const now=()=>new Date().toISOString();
const digest=v=>crypto.createHash('sha256').update(v).digest('hex');
const abortError=reason=>Object.assign(new Error(reason),{name:'AbortError'});
const allowedHost=u=>['threads.net','www.threads.net','threads.com','www.threads.com'].includes(new URL(u).hostname);

export function authorizationReasons(config, at=new Date()) {
  const a=config.authorization;
  const out=[];
  if(a?.status!=='approved')out.push('method_not_approved');
  if(!a?.approved_methods?.includes('ckelepel-public-http'))out.push('approval_does_not_cover_this_collector');
  if(!a?.evidence_file)out.push('approval_evidence_missing');
  if(!a?.valid_until_utc || !(new Date(a.valid_until_utc)>at))out.push('approval_expired_or_missing_expiry');
  return out;
}

export function boundedTransport(options) {
  const state={httpRequestCount:0,fatal:null,lastRequestMs:0,attempts:[],archive:[]};
  let queue=Promise.resolve();
  const fail=(code,message)=>{state.fatal??={code,message};throw abortError(message);};
  const event=async e=>{
    state.attempts.push(e);
    if(options.journal)await fs.appendFile(options.journal,JSON.stringify(e)+'\n');
  };
  async function one(url, init) {
    if(state.fatal)throw abortError(state.fatal.message);
    if(init.signal?.aborted)throw abortError('collector_cancelled_after_limit');
    if(!allowedHost(url))return fail('UNAPPROVED_HOST','URL host is outside the authorized Threads surface');
    if(state.httpRequestCount>=options.maxRequests)return fail('REQUEST_BUDGET','HTTP request budget reached');
    const delay=Math.max(0,options.minimumIntervalMs-(Date.now()-state.lastRequestMs));
    if(delay)await new Promise(r=>setTimeout(r,delay));
    if(state.fatal)throw abortError(state.fatal.message);
    if(init.signal?.aborted)throw abortError('collector_cancelled_after_limit');
    const n=++state.httpRequestCount;
    state.lastRequestMs=Date.now();
    const start=now();
    const headers={...init.headers};
    for(const k of Object.keys(headers))if(/cookie|authorization/i.test(k))delete headers[k];
    headers['User-Agent']='PxmartAcademicDataFeasibility/1.0 (bounded public research test)';
    // The transport ignores SDK dispatchers/proxy/cookie options and never impersonates a login.
    const req={method:init.method||'GET',headers,body:init.body,redirect:'manual',
      signal:AbortSignal.any([AbortSignal.timeout(options.timeoutMs),...(init.signal?[init.signal]:[])])};
    await event({type:'HTTP_REQUEST_STARTED',request_id:n,url:String(url),method:req.method,request_started_at:start});
    let response;
    try {response=await options.fetchImpl(url,req);}
    catch(error){
      if(init.signal?.aborted && !state.fatal)throw abortError('collector_cancelled_after_limit');
      await event({type:'HTTP_ERROR',request_id:n,error_type:error.name,response_received_at:null});
      return fail('NETWORK_OR_TIMEOUT',error.name||'network error');
    }
    const chunks=[];let bytes=0;
    try {
      for await(const chunk of response.body||[]) {
        bytes+=chunk.length;
        if(bytes>options.maxBytes) return fail('RESPONSE_SIZE','response exceeds configured bound');
        chunks.push(chunk);
      }
    }catch(error){return fail(state.fatal?.code||'RESPONSE_READ',error.message);}
    const body=Buffer.concat(chunks);const received=now();
    let rawPath=null;
    if(options.archiveDir){
      rawPath=path.join(options.archiveDir,`http_${String(n).padStart(3,'0')}.body`);
      await fs.writeFile(rawPath,body);
    }
    const entry={request_id:n,url:String(url),method:req.method,request_started_at:start,
      response_received_at:received,http_status:response.status,bytes:body.length,sha256:digest(body),raw_path:rawPath};
    state.archive.push({...entry,body_text:body.toString('utf8')});
    await event({type:'HTTP_RESPONSE_RECEIVED',...entry});
    if(response.status>=400)return fail(response.status===429?'RATE_LIMIT':'HTTP_ERROR',`HTTP ${response.status}; no retry`);
    if(response.status>=300&&response.status<400){
      const next=response.headers.get('location');
      if(!next)return fail('REDIRECT_ERROR','redirect without location');
      const target=new URL(next,url).href;
      if(!allowedHost(target))return fail('UNAPPROVED_REDIRECT','redirect leaves the approved host allowlist');
      return one(target,{...init,method:'GET',body:undefined}); // counts redirects against the same budget
    }
    const text=body.toString('utf8');
    if(/checkpoint_required|challenge_required|g-recaptcha|hcaptcha|<title[^>]*>\s*(?:log in|login|登入)/i.test(text))
      return fail('ACCESS_CHALLENGE','login/checkpoint/captcha challenge; stopped');
    if(text.trim().startsWith('{')){
      try {const j=JSON.parse(text);if(j.error || (Array.isArray(j.errors)&&j.errors.length))return fail('UPSTREAM_ERROR','JSON/GraphQL error payload');}
      catch(error){if(error.name==='AbortError')throw error;return fail('INVALID_RESPONSE_JSON','JSON body could not be parsed');}
    }
    return new Response(body,{status:response.status,headers:response.headers});
  }
  const fetchFn=(url,init={})=>{
    const result=queue.then(()=>one(url,init)).catch(error=>{
      if(error.name==='AbortError')throw error;
      state.fatal??={code:'TRANSPORT_FAILURE',message:error.message};
      throw abortError(state.fatal.message);
    });
    queue=result.catch(()=>{});
    return result;
  };
  return {state,fetchFn};
}

export async function runQuery(config, spec, deps={}) {
  const settings=config.stages?.[spec.stage];
  if(!settings || !config.keywords?.[settings.keywords]?.includes(spec.keyword) ||
     !Number.isInteger(spec.limit) || spec.limit<1 || spec.limit>settings.limit_per_query ||
     !Number.isInteger(spec.max_http_requests) || spec.max_http_requests<1 || spec.max_http_requests>settings.max_http_per_query)
    throw Error('QUERY_CONFIG_OUT_OF_BOUNDS');
  const reasons=authorizationReasons(config);
  if(reasons.length)return {status:'BLOCKED_AUTHORIZATION',network_executed:false,http_request_count:0,errors:reasons,exit_code:2};
  const evidence=await fs.readFile(config.authorization.evidence_file);
  if(!evidence.length)throw Error('empty authorization evidence');
  const tool=config.tool;
  for(const [file,expected] of Object.entries(tool.sha256)) {
    if(digest(await fs.readFile(path.join(tool.installed_path,file)))!==expected)
      throw Error('TOOL_PIN_MISMATCH: '+file);
  }
  const pkg=JSON.parse(await fs.readFile(path.join(tool.installed_path,'package.json'),'utf8'));
  if(pkg.version!==tool.package_version)throw Error('TOOL_PACKAGE_VERSION_MISMATCH');
  // Clean inherited session/proxy settings before importing the collector.
  for(const k of Object.keys(process.env))if(/cookie|proxy|access_token/i.test(k))delete process.env[k];
  const {searchThreads}=await import(pathToFileURL(path.join(tool.installed_path,'src/scraper.js')));
  const {extractPostsFromHtml,normalizePost}=await import(pathToFileURL(path.join(tool.installed_path,'src/normalizers.js')));
  await fs.mkdir(spec.raw_dir,{recursive:true});
  const transport=boundedTransport({maxRequests:spec.max_http_requests,minimumIntervalMs:config.stopping.minimum_http_interval_seconds*1000,
    timeoutMs:config.stopping.single_http_timeout_seconds*1000,maxBytes:config.stopping.max_response_bytes,
    fetchImpl:deps.fetchImpl||globalThis.fetch,journal:path.join(spec.raw_dir,'requests.jsonl'),archiveDir:spec.raw_dir});
  const started=now();let result=null;let engineError=null;
  try {result=await searchThreads(spec.keyword,{limit:spec.limit,expand:false,strict:true,fetchFn:transport.fetchFn});}
  catch(error){engineError={name:error.name,message:error.message};}
  const finished=now();
  const status=transport.state.fatal||engineError?'FAILED':Array.isArray(result?.results)?(result.results.length?'SUCCESS':'EMPTY'):'INVALID_COLLECTOR_OUTPUT';
  const observations=[];
  for(const entry of transport.state.archive) {
    if(entry.http_status!==200)continue;
    let parsed=[];
    if(entry.body_text.trim().startsWith('<'))parsed=extractPostsFromHtml(entry.body_text);
    else {try {
      const j=JSON.parse(entry.body_text);const connection=j?.data?.xdt_api__v1__text_feed__search_results__connection_v2||j?.data?.searchResults;
      parsed=(connection?.edges||[]).map(e=>normalizePost(e.node?.thread?.thread_items?.[0]?.post||e.node?.thread_items?.[0]?.post)).filter(Boolean);
    }catch{}}
    for(const p of parsed)observations.push({id:p.id,text:p.caption,like_count:p.like_count,reply_count:p.reply_count,repost_count:p.repost_count,quote_count:p.quote_count,
      response_received_at:entry.response_received_at,request_started_at:entry.request_started_at,raw_http_ref:entry.raw_path,request_id:entry.request_id});
  }
  const archive=transport.state.archive.map(({body_text,...entry})=>entry);
  const metadata={status,keyword:spec.keyword,limit:spec.limit,collector:'ckelepel-threads',package_version:pkg.version,exported_version:tool.exported_version,
    tool_commit:tool.git_commit,authorization_evidence_sha256:digest(evidence),request_started_at:started,finished_at:finished,
    http_request_count:transport.state.httpRequestCount,simulation:Boolean(deps.fetchImpl),
    network_executed:!deps.fetchImpl&&transport.state.httpRequestCount>0,
    error:transport.state.fatal||engineError,http_responses:archive,result_observations:observations,
    recent_search_verified:false,native_date_filter:false,automatic_expansion:false,automatic_retry:false,
    cli_equivalent:['search',spec.keyword,'--limit',String(spec.limit),'--no-expand','--json'],exit_code:['SUCCESS','EMPTY'].includes(status)?0:1};
  // SDK result is preserved independently of wrapper validation status.
  await fs.writeFile(spec.result_path,JSON.stringify(result,null,2));
  await fs.writeFile(spec.metadata_path,JSON.stringify(metadata,null,2));
  return metadata;
}

if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href){
  try {
    const config=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
    const spec=JSON.parse(await fs.readFile(process.argv[3],'utf8'));
    const m=await runQuery(config,spec);
    console.log(JSON.stringify(m));process.exitCode=m.exit_code;
  }catch(error){console.error(JSON.stringify({status:'WORKER_FAILED',error:error.message}));process.exitCode=1;}
}
