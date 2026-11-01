#!/usr/bin/env python3
"""One official read-only request. Dry-run by default; no cookies, retries or paging."""
import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core import utc_now

ROOT=Path(__file__).resolve().parents[1]


def plan(config, mode='search', keyword='全聯', thread_id=None, token_present=False):
    required = 'threads_keyword_search' if mode=='search' else 'threads_read_replies' if mode=='replies' else 'threads_basic'
    missing=[]
    if required not in config.get('approved_api_permissions',[]):
        missing.append('permission_not_confirmed:'+required)
    if not config.get('research_use_approved'):
        missing.append('research_use_not_confirmed')
    if not config.get('approval_evidence_ref'):
        missing.append('local_approval_evidence_ref_missing')
    if mode=='search' and not config.get('app_review_approved'):
        missing.append('public_keyword_search_app_review_not_approved')
    if mode=='replies' and thread_id not in config.get('reply_access_approved_ids',[]):
        missing.append('this_thread_reply_access_not_confirmed')
    if not token_present:
        missing.append('environment_token_missing')
    if mode=='replies' and not re.fullmatch(r'\d+',thread_id or ''):
        missing.append('invalid_thread_id')
    params={'fields':'id,text,timestamp,permalink','limit':'10' if mode=='replies' else '15'}
    endpoint='keyword_search' if mode=='search' else f'{thread_id}/replies' if mode=='replies' else 'me/threads'
    if mode=='search':
        if keyword not in config['keywords']:
            missing.append('keyword_outside_bounded_plan')
        params.update(q=keyword,search_type='TOP')
    return dict(status='BLOCKED' if missing else 'READY',blocking_reasons=missing,mode=mode,
                method='GET',host='graph.threads.net',endpoint=endpoint,params=params,
                request_budget=1,automatic_pagination=False,automatic_retry=False,
                authorization_in_env_only=True,record_received_time_as_observation=True,
                note='TOP is in Meta official Postman sample. RECENT/date parameters remain unverified here.')


def response_envelope(p, raw_bytes, http_status, started, received):
    try:
        payload=json.loads(raw_bytes)
    except (ValueError,UnicodeError):
        payload={'error':{'type':'non_json_response'}}
    values=payload.get('data')
    status='FAILED'
    if http_status==200 and isinstance(values,list) and 'error' not in payload:
        status='SUCCESS' if values else 'EMPTY'
    run=dict(run_id='official_'+hashlib.sha256((started+p['endpoint']).encode()).hexdigest()[:20],
             collector='Meta Threads API',collector_version=None,collection_method='keyword_search' if p['mode']=='search' else 'replies' if p['mode']=='replies' else 'profile',
             search_keywords=[p['params']['q']] if 'q' in p['params'] else [],
             query_config=p['params'], request_started_at=started,response_received_at=received,
             actual_fetched_at_utc=received,status=status,http_status=http_status,
             result_count=len(values) if isinstance(values,list) else None,network_executed=True,
             observed_at_definition='本機收到完整回應的時間；不是伺服器端精確觀測時刻')
    return dict(run=run,response=payload,raw_utf8=raw_bytes.decode('utf-8',errors='replace'),raw_sha256=hashlib.sha256(raw_bytes).hexdigest())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def execute(p, token, transport=None):
    if p['status']!='READY':
        raise PermissionError('No network request: '+','.join(p['blocking_reasons']))
    url='https://graph.threads.net/'+p['endpoint']+'?'+urllib.parse.urlencode(p['params'])
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    started=utc_now()
    call=transport or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open
    try:
        with call(req,timeout=20) as response:
            body=response.read(5_000_001)
            code=response.status
    except urllib.error.HTTPError as e:
        body=e.read(5_000_001)
        code=e.code
    except (urllib.error.URLError,TimeoutError,OSError):
        method='keyword_search' if p['mode']=='search' else 'replies' if p['mode']=='replies' else 'profile'
        return dict(run=dict(run_id='failed_'+started,collector='Meta Threads API',collection_method=method,status='FAILED',request_started_at=started,response_received_at=None,result_count=None,network_executed=True),response={'error':{'type':'network_error'}},raw_utf8=None)
    received=utc_now()
    if len(body)>5_000_000:
        body=b'{"error":{"type":"response_size_limit_exceeded"}}'
        code=413
    # Do not persist secrets potentially echoed in paging URLs/errors.
    original_sha=hashlib.sha256(body).hexdigest()
    clean=body.replace(token.encode(),b'[REDACTED]')
    result=response_envelope(p,clean,code,started,received)
    result['original_response_sha256']=original_sha
    result['credential_redaction_applied']=clean!=body
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',type=Path,default=ROOT/'config/run.json')
    ap.add_argument('--mode',choices=['own','search','replies'],default='search')
    ap.add_argument('--keyword',default='全聯')
    ap.add_argument('--thread-id')
    ap.add_argument('--execute',action='store_true')
    a=ap.parse_args()
    config=json.loads(a.config.read_text())
    token=os.environ.get(config.get('token_env_name','THREADS_ACCESS_TOKEN'),'')
    p=plan(config,a.mode,a.keyword,a.thread_id,bool(token))
    if not a.execute:
        saved_plan=ROOT/'internal/official_probe_plan.json'
        saved_plan.parent.mkdir(parents=True,exist_ok=True)
        saved_plan.write_text(json.dumps({'planned_at_utc':utc_now(),'network_executed':False,**p},ensure_ascii=False,indent=2))
        print(json.dumps(p,ensure_ascii=False,indent=2))
    else:
        if p['status']!='READY':
            print(json.dumps(p,ensure_ascii=False,indent=2))
            raise SystemExit(2)
        # Persist a shared budget per configured run. A small output limit is not a request budget.
        ledger_path=ROOT/'internal/official_request_budget.json'
        ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        key=config['run_started_at_utc']
        budget=ledger.setdefault(key,{'requests':0,'search_requests':0,'last_request_epoch':0,'stopped':False})
        limits=config['bounded_test']
        if budget['stopped'] or budget['requests']>=limits['max_http_requests'] or (a.mode=='search' and budget['search_requests']>=limits['max_search_requests']):
            raise SystemExit('STOPPED: bounded request budget or access restriction reached')
        if time.time()-budget['last_request_epoch']<limits['minimum_interval_seconds']:
            raise SystemExit('STOPPED: respect minimum request interval before another request')
        budget['requests']+=1
        budget['search_requests']+=int(a.mode=='search')
        budget['last_request_epoch']=time.time()
        ledger_path.write_text(json.dumps(ledger,indent=2))
        result=execute(p,token)
        if result['run'].get('http_status') in (401,403,429):
            budget['stopped']=True
        ledger_path.write_text(json.dumps(ledger,indent=2))
        dest=ROOT/'internal/official_responses'/f'{result["run"]["run_id"].replace(":","-")}.json'
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({'status':result['run']['status'],'result_count':result['run']['result_count'],'saved_to':str(dest)},ensure_ascii=False))
        if result['run']['status']=='FAILED':
            raise SystemExit(1)
