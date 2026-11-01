#!/usr/bin/env python3
"""Repeatable local experiment. Default is offline; no scheduler is installed."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data_pipeline import ROOT, load_json, sha, parse_time, utc_now, connect, records, known_ids, ingest, batch_metrics, dataset_summary, validate_payload, refresh_assessments


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def resolve(root,value):
    p=Path(value)
    return p if p.is_absolute() else (root/p).resolve()


def configuration(path):
    cfg=load_json(path)
    if cfg['default_mode'] not in ('offline','live'):
        raise ValueError('invalid default_mode')
    if cfg['stopping']['concurrency']!=1 or cfg['stopping']['automatic_retry'] or cfg['stopping']['automatic_topic_expansion']:
        raise ValueError('only sequential, no-retry, no-auto-expansion mode is permitted')
    if cfg['stopping']['minimum_http_interval_seconds']<5:
        raise ValueError('minimum HTTP interval must be at least five seconds')
    for name,s in cfg['stages'].items():
        if name=='C':
            continue
        if not 1<=s['limit_per_query']<=100 or not 1<=s['max_queries']<=12 or not 1<=s['max_http_requests']<=80 or not 1<=s['max_http_per_query']<=10:
            raise ValueError('out-of-bound configuration')
        words=cfg['keywords'][s['keywords']]
        if len(words)!=len(set(words)) or any(not isinstance(k,str) or not k.strip() or ',' in k for k in words):
            raise ValueError('query list must contain separate non-empty keywords, not comma fan-out')
    return cfg


def authorization_reasons(cfg,root):
    a=cfg['authorization'];out=[]
    if a.get('status')!='approved':out.append('尚無核准來源')
    if 'ckelepel-public-http' not in a.get('approved_methods',[]):out.append('尚無涵蓋此 HTML/GraphQL 工具的適用許可')
    evidence=a.get('evidence_file')
    if not evidence or not resolve(root,evidence).is_file():out.append('本機核准證據不存在')
    until=parse_time(a.get('valid_until_utc'))
    if until is None or until<=parse_time(utc_now()):out.append('許可效期未確認或已過期')
    return out


def environment_audit(root,network=True,tool=None,approval_context='default'):
    workspace=root.parent
    commands={}
    for args in (['pwd'],['node','-v'],['npm','-v'],['which','npx'],['git','--version']):
        try:
            p=subprocess.run(args,cwd=workspace,capture_output=True,text=True,timeout=20)
            commands[' '.join(args)]=dict(exit_code=p.returncode,stdout=p.stdout.strip(),stderr=p.stderr.strip())
        except (OSError,subprocess.TimeoutExpired) as e:
            commands[' '.join(args)]={'exit_code':None,'error_type':type(e).__name__}
    probe=root/'data/write_permission_probe.txt'
    probe.parent.mkdir(parents=True,exist_ok=True)
    probe.write_text('Local experiment write/read check\n',encoding='utf-8')
    write_ok=probe.read_text()=='Local experiment write/read check\n'
    github={'status':'NOT_TESTED'}
    if network:
        # Public repository metadata only. This is not a Threads content request.
        p=subprocess.run(['curl','-fsSL','--max-time','15','https://api.github.com/repos/wongedyan/ckelepel-threads'],capture_output=True,text=True,timeout=20)
        github={'exit_code':p.returncode,'status':'PASS' if p.returncode==0 else 'NETWORK_ENVIRONMENT_ERROR'}
        if p.returncode==0:
            d=json.loads(p.stdout)
            github.update(repository=d['full_name'],private=d['private'],default_branch=d['default_branch'],response_sha256=sha(p.stdout.encode()))
            write_json(root/'data/github_repository_metadata.json',d)
        else:
            github['stderr']=p.stderr[:500]
    tool_check={'status':'NOT_TESTED'}
    if tool:
        try:
            base=Path(tool['installed_path'])
            actual={f:sha((base/f).read_bytes()) for f in tool['sha256']}
            tool_check={'status':'PASS' if actual==tool['sha256'] else 'TOOL_PIN_MISMATCH','package_version':load_json(base/'package.json')['version'],
                        'exported_version':tool['exported_version'],'git_commit':tool['git_commit'],'file_sha256':actual}
            help_run=subprocess.run([tool['node_binary'],str(base/'bin/ckelepel.js'),'search','--help'],capture_output=True,text=True,timeout=20)
            tool_check.update(cli_help_exit_code=help_run.returncode,cli_help_stdout=help_run.stdout,cli_help_stderr=help_run.stderr)
            if help_run.returncode:tool_check['status']='CLI_RUNTIME_ERROR'
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
            tool_check={'status':'LOCAL_TOOL_ERROR','error_type':type(error).__name__,'error':str(error)}
    return dict(checked_at_utc=utc_now(),commands=commands,tool=tool_check,read_workspace=(workspace/'threads-poc-v05/output/threads_raw_v05.json').is_file(),
                write_experiment=write_ok,github=github,network_execution_context=approval_context,
                additional_approval_needed_for_this_github_check=True if approval_context=='codex-approved' else None,
                sandbox_approval_mechanism='Codex 正常 require_escalated；核准情境只記錄執行方式，不代表 Threads 資料許可',
                platform_authorization_is_separate=True,
                credentials_configured={k:bool(os.environ.get(k)) for k in ('THREADS_ACCESS_TOKEN','INFOMINER_API_KEY','LARGITDATA_API_KEY')})


def import_existing(cfg,root,db,review):
    legacy_path=resolve(root,cfg['legacy_bundle'])
    bundle=load_json(legacy_path)
    old=bundle['raw_responses'][0]['response']
    old_bytes=bundle['raw_responses'][0].get('raw_utf8')
    old_bytes=old_bytes.encode() if old_bytes is not None else json.dumps(old,ensure_ascii=False).encode()
    if bundle['raw_responses'][0].get('sha256')!=sha(old_bytes):
        raise ValueError('legacy raw UTF-8 integrity check failed')
    new_path=resolve(root,cfg['recorded_batch']);new_bytes=new_path.read_bytes();new=json.loads(new_bytes)
    start_path=resolve(root,cfg['recorded_start']);finish_path=resolve(root,cfg['recorded_finish'])
    start=parse_time(start_path.read_text().strip());finish=parse_time(finish_path.read_text().strip())
    if start is None or finish is None or finish<start:
        raise ValueError('invalid supplied batch start/finish times')
    for doc in (old,new):
        if validate_payload(doc):raise ValueError(str(validate_payload(doc)))
    baseline={f'threads:post:{p["id"]}' for p in old['results']}
    old_metrics=batch_metrics(old,review,set(),set(),start)
    old_brand={r['record_id'] for r in old_metrics['review_pending_rows'] if r['brand_candidate']}
    second_metrics=batch_metrics(new,review,baseline,old_brand,start)
    imported=0
    before_ids=known_ids(db)
    source_info=[]
    for label,doc,body,p,window_start,window_end,basis in (
        ('legacy',old,old_bytes,legacy_path,None,None,'unknown_legacy'),
        ('recorded_batch',new,new_bytes,new_path,start.isoformat(),finish.isoformat(),'supplied_outer_cli_window; not exact HTTP receipt')):
        archive=root/'data/input_archive'/f'{label}_{sha(body)}.json'
        archive.parent.mkdir(parents=True,exist_ok=True)
        if archive.exists() and archive.read_bytes()!=body:
            raise ValueError('archive collision')
        if not archive.exists():archive.write_bytes(body)
        sid=label+'_'+sha(body+(window_start or '').encode()+(window_end or '').encode())[:24]
        info=dict(source_id=sid,input_path=str(p),archive_path=str(archive),sha256=sha(body),origin=label,
                  reference_utc=start.isoformat(),start_utc=window_start,finish_utc=window_end,time_basis=basis,
                  collector_version=None,exact_received_at_utc=None,
                  notes='User-supplied existing capture; not fetched by this experiment')
        if label=='legacy':
            info['parent_container_sha256']=sha(legacy_path.read_bytes())
            info['raw_pointer_in_container']='raw_responses[0].response'
        else:
            info['timestamp_file_evidence']={str(p):sha(p.read_bytes()) for p in (start_path,finish_path)}
        imported+=int(ingest(db,doc,info,review,{r['record_id']:r for r in bundle['normalized_records']}))
        source_info.append(info)
    return dict(old=old_metrics,second=second_metrics,
                union_unique_candidate_ids=len(baseline|{f'threads:post:{p["id"]}' for p in new['results']}),
                source_info=source_info,provided_capture_duration_seconds=(finish-start).total_seconds(),
                newly_imported_sources_this_execution=imported,new_record_ids_inserted_this_execution=len(known_ids(db)-before_ids),
                new_threads_http_requests_by_codex=0,
                historical_second_batch_is_existing_user_capture=True)


def planned_stage(cfg,root,stage,db):
    if stage=='C':
        return dict(stage='C',status='DESIGN_ONLY',scheduler_installed=False,queries=[],
                    definition='經授權後每 60 分鐘固定查詢、保存搜尋範圍與每次互動快照；本輪沒有安裝排程')
    settings=cfg['stages'][stage]
    words=cfg['keywords'][settings['keywords']][:settings['max_queries']]
    blocks=authorization_reasons(cfg,root)
    if stage=='B':
        passed=db.execute("SELECT execution_id FROM stage_results WHERE stage='A' AND status='PASS' ORDER BY created_at DESC LIMIT 1").fetchone()
        if not passed:blocks.append('Stage A 尚未通過實際有界搜尋與品質驗收')
        if dataset_summary(db)['human_confirmed_brand_count']<settings['min_human_confirmed_records']:
            blocks.append('Stage B 所需人工確認樣本不足')
        release=settings.get('release_evidence_file')
        if not release or not resolve(root,release).is_file():blocks.append('尚無 Stage A 品質複核與 Stage B 放行紀錄')
        else:
            try:
                decision=load_json(resolve(root,release))
                if not passed or decision.get('stage_a_execution_id')!=passed[0] or not decision.get('approved_by') or not parse_time(decision.get('reviewed_at_utc')):
                    blocks.append('Stage B 放行紀錄未對應本次 Stage A／人工審核')
            except (ValueError,TypeError):blocks.append('Stage B 放行紀錄格式無效')
    queries=[dict(index=i+1,keyword=k,tier=settings['keywords'],limit=settings['limit_per_query'],
                  cli_equivalent=['search',k,'--limit',str(settings['limit_per_query']),'--no-expand','--json'],
                  status='BLOCKED_AUTHORIZATION' if authorization_reasons(cfg,root) else 'PLANNED',
                  expected_new_brand_candidates=None) for i,k in enumerate(words)]
    return dict(stage=stage,status='BLOCKED_AUTHORIZATION' if authorization_reasons(cfg,root) else 'BLOCKED_STAGE_GATE' if blocks else 'READY',
                blockers=blocks,queries=queries,max_http_requests=settings['max_http_requests'],
                max_output_rows=len(words)*settings['limit_per_query'],
                note='每個 CLI 查詢可能發出多個 HTTP／重新導向；按 HTTP 逐次計數。近期與日期篩選僅在本機執行。')


def stopping_reason(metrics,cfg,no_gain_count):
    if metrics.get('status') not in ('VALID','VALID_EMPTY'):
        return 'INVALID_JSON_STRUCTURE'
    n=metrics['unique_ids']
    if n and metrics['brand_candidate_count']/n<cfg['stopping']['min_valid_brand_fraction']:
        return 'LOW_BRAND_RELEVANCE_REVIEW_REQUIRED'
    if n and metrics['relevance_counts']['uncertain']/n>cfg['stopping']['max_uncertain_fraction']:
        return 'UNCERTAIN_CONTENT_REVIEW_REQUIRED'
    if no_gain_count>=cfg['stopping']['consecutive_zero_new_brand_queries']:
        return 'CONSECUTIVE_ZERO_NEW_BRAND_CANDIDATES'
    if metrics['missing_or_future_timestamp_count']:
        return 'INVALID_PUBLISH_TIME_REVIEW_REQUIRED'
    return None


def query_log(db,execution,stage,item,report):
    rid=execution+'_'+str(item['index'])
    with db:
        db.execute('INSERT INTO query_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (rid,stage,item['keyword'],report.get('request_started_at'),report.get('finished_at'),report['status'],report.get('exit_code'),report.get('http_request_count',0),report.get('result_path'),json.dumps(report,ensure_ascii=False)))


def run_live_stage(cfg,config_path,root,db,review,plan,execution,directory):
    if plan['status']!='READY':
        for item in plan.get('queries',[]):query_log(db,execution,plan['stage'],item,{'status':plan['status'],'http_request_count':0,'network_executed':False})
        return {'status':plan['status'],'query_results':[],'http_request_count':0,'blockers':plan.get('blockers',[])}
    settings=cfg['stages'][plan['stage']]
    budget=settings['max_http_requests'];total=0;new_ids=0;stalls=0;results=[];stop=None
    resolved=json.loads(json.dumps(cfg))
    resolved['authorization']['evidence_file']=str(resolve(root,cfg['authorization']['evidence_file']))
    runtime_cfg=directory/'runtime_config.json';write_json(runtime_cfg,resolved)
    safe_env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
    for item in plan['queries']:
        if total>=budget:stop='HTTP_BUDGET';break
        if new_ids>=settings['max_new_candidate_ids']:stop='UNIQUE_CANDIDATE_BUDGET';break
        if results:time.sleep(cfg['stopping']['minimum_query_interval_seconds'])
        qdir=directory/'queries'/f'{item["index"]:02d}_{sha(item["keyword"].encode())[:10]}'
        qdir.mkdir(parents=True,exist_ok=True)
        spec=dict(keyword=item['keyword'],stage=plan['stage'],limit=item['limit'],max_http_requests=min(settings['max_http_per_query'],budget-total),
                  raw_dir=str(qdir/'http'),result_path=str(qdir/'search_response.json'),metadata_path=str(qdir/'collection_manifest.json'))
        write_json(qdir/'request_spec.json',spec)
        started=utc_now()
        try:
            p=subprocess.run([cfg['tool']['node_binary'],str(root/'scripts/bounded_search.mjs'),str(runtime_cfg),str(qdir/'request_spec.json')],
                capture_output=True,text=True,env=safe_env,timeout=cfg['stopping']['query_timeout_seconds'])
            (qdir/'stdout.txt').write_text(p.stdout);(qdir/'stderr.txt').write_text(p.stderr)
            metadata=load_json(spec['metadata_path']) if Path(spec['metadata_path']).is_file() else {'status':'WORKER_FAILED','http_request_count':0,'error':p.stderr[:500]}
            metadata.update(exit_code=p.returncode,result_path=spec['result_path'])
        except subprocess.TimeoutExpired as e:
            (qdir/'stdout.txt').write_text((e.stdout or b'').decode() if isinstance(e.stdout,bytes) else e.stdout or '')
            (qdir/'stderr.txt').write_text('TIMEOUT; process stopped')
            metadata={'status':'TIMEOUT','exit_code':None,'http_request_count':0,'error':'query timeout'}
        except OSError as error:
            (qdir/'stderr.txt').write_text(str(error))
            metadata={'status':'LOCAL_EXECUTION_ERROR','exit_code':None,'http_request_count':0,'error':str(error)}
        journal=qdir/'http/requests.jsonl'
        events=[json.loads(x) for x in journal.read_text().splitlines() if x] if journal.exists() else []
        physical=sum(e.get('type')=='HTTP_REQUEST_STARTED' for e in events)
        metadata.update(http_request_count=physical,request_started_at=started,finished_at=utc_now())
        total+=physical
        if metadata.get('simulation'):
            metadata['status']='MOCK_NOT_RESEARCH_DATA'
        if metadata['status'] not in ('SUCCESS','EMPTY') or metadata['exit_code']!=0:
            stop=metadata.get('error') or metadata['status']
        else:
            doc=load_json(spec['result_path'])
            metrics=batch_metrics(doc,review,known_ids(db),known_ids(db,True),parse_time(started))
            metadata['yield_metrics']=metrics
            if metrics['status'] not in ('VALID','VALID_EMPTY'):
                metadata['status']='INVALID_JSON_STRUCTURE';stop='INVALID_JSON_STRUCTURE'
            else:
                source=dict(source_id=execution+'_'+str(item['index']),input_path=spec['result_path'],sha256=sha(Path(spec['result_path']).read_bytes()),
                            origin='live_experiment',start_utc=started,finish_utc=metadata['finished_at'],time_basis='instrumented_http_receipts_per_post',
                            exact_received_at_utc=None,collector_version=cfg['tool']['package_version'],per_post_observations=metadata.get('result_observations',[]))
                ingest(db,doc,source,review)
                new_ids+=metrics['new_id_count'];stalls=stalls+1 if metrics['newly_retrieved_brand_count']==0 else 0
                stop=stopping_reason(metrics,cfg,stalls)
        query_log(db,execution,plan['stage'],item,metadata)
        write_json(qdir/'query_result.json',metadata)
        results.append(metadata)
        if stop:break
    passed=not stop and len(results)==len(plan['queries']) and any(r.get('yield_metrics',{}).get('newly_retrieved_brand_count',0)>0 for r in results)
    return dict(status='PASS' if passed else 'STOPPED' if stop else 'INSUFFICIENT_GAIN',query_results=results,http_request_count=total,stop_reason=stop,
                stage_pass_meaning='搜尋執行、JSON、時間與最低相關性／增益檢查通過；不代表全平台覆蓋或模型可行')


def render_summary(analysis,plans,stage_result,environment):
    b=analysis['two_batch_validation'];s=analysis['dataset'];second=b['second'];c=s['relevance_counts']
    command_results='\n'.join(f'{k}: {v.get("stdout",v.get("error_type","ERROR"))}' for k,v in environment['commands'].items())
    source=b['source_info'][1]
    start_tw=parse_time(source['start_utc']).astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y/%m/%d %H:%M:%S')
    conditions=analysis['experiment_conditions'];stage_a=conditions['stages']['A'];stage_b=conditions['stages']['B'];stop=conditions['stopping']
    permission_note='Codex 核准後執行；預設沙盒內子程序曾遇到 DNS 限制，失敗紀錄已保留。' if environment.get('network_execution_context')=='codex-approved' else '執行情境如 environment.json；網路失敗不歸類為 Threads 授權錯誤。'
    return f'''# 全聯 Threads 蒐集前置實驗

本機 Terminal / Node / 讀寫已分別執行；GitHub 檢查：{environment['github']['status']}。{permission_note}本輪 Threads HTTP 請求 {stage_result['http_request_count']} 次，未安裝排程。

```text
{command_results}
```

固定工具與 CLI Help 校驗：{environment.get('tool',{}).get('status','NOT_TESTED')}。

## 兩批既有真實紀錄

| 指標 | 數值 |
|---|---:|
| 第一批唯一 ID | {b['old']['unique_ids']} |
| 第二批唯一 ID | {second['unique_ids']} |
| 交集 | {second['cross_batch_duplicate_count']} |
| 第二批新增 ID | {second['new_id_count']} |
| 聯集候選 ID | {b['union_unique_candidate_ids']} |
| 第二批品牌候選（直接＋間接） | {second['brand_candidate_count']} |
| 第二批新 ID 中的品牌候選 | {second['newly_retrieved_brand_count']} |
| 目前資料庫直接品牌候選 | {s['direct_brand_candidate_count']} |
| 目前資料庫間接品牌候選 | {c.get('related',0)} |
| 僅背景／地點 | {c.get('context_only',0)} |
| 品牌相關性待判定 | {c.get('uncertain',0)} |
| 人工確認品牌貼文 | {s['human_confirmed_brand_count']} |

品牌候選共 {s['brand_candidate_count']} 篇，是保守文字篩選的待人工研究樣本；不能將 37 個 ID 一律稱為品牌有效資料。標註維持 pending，未把程式審查冒充研究者確認。排除例：淡江大學冰箱抱怨、唱歌邀約與發飄帶集合地點；寶雅商圈／全聯關店另列間接相關。

第二批以其開始時間 {second['reference_at_utc']}（台灣時間 {start_tw}）為基準：

| 時窗 | 全部第二批貼文 | 品牌候選（直接＋間接） | 僅直接品牌候選 |
|---|---:|---:|---:|
| 12 小時 | {second['published_time_counts']['12h']} | {second['brand_candidate_time_counts']['12h']} | {second['direct_time_counts']['12h']} |
| 24 小時 | {second['published_time_counts']['24h']} | {second['brand_candidate_time_counts']['24h']} | {second['direct_time_counts']['24h']} |
| 7 天 | {second['published_time_counts']['7d']} | {second['brand_candidate_time_counts']['7d']} | {second['direct_time_counts']['7d']} |
| 30 天 | {second['published_time_counts']['30d']} | {second['brand_candidate_time_counts']['30d']} | {second['direct_time_counts']['30d']} |

第二批時窗為 {source['start_utc']} 至 {source['finish_utc']}、{b['provided_capture_duration_seconds']} 秒。這是使用者提供的外層 CLI 起訖紀錄，非每篇 HTTP 精確收取時間；actual_fetched_at 仍不猜填，快照另外保留該區間。舊批次觀測時刻未知。taken_at 來自工具回傳；上游缺時間可能補當下，解析成功不等於已獨立查證發文時間。

## 自動化與三階段驗收

- Stage A：核心查詢最多 {stage_a['max_queries']} 組，每組最多 {stage_a['limit_per_query']} 筆；總 HTTP 上限 {stage_a['max_http_requests']}，單查詢上限 {stage_a['max_http_per_query']}，序列執行、至少間隔 {stop['minimum_http_interval_seconds']} 秒、無自動重試／擴詞；本機日期過濾不是原生 Recent 搜尋。遇到 401/403/429、登入／驗證、錯誤、預算耗盡或連續 {stop['consecutive_zero_new_brand_queries']} 查詢零新增品牌樣本即停止。計畫狀態：{plans['A']['status']}。
- Stage B：Stage A 實測通過、至少 {stage_b['min_human_confirmed_records']} 筆人工確認與品質放行後，才加入延伸詞。每次查詢都先計算邊際增益與品質，最多 {stage_b['max_queries']} 個詞各 {stage_b['limit_per_query']} 筆。100／300／500 是探索目標；本設定單輪至多回傳 {plans['B']['max_output_rows']} 筆、且有重複，不能保證 500。計畫狀態：{plans['B']['status']}。
- Stage C：只保存每小時定期觀測設計，scheduler_installed=false；相同 record_id 不變，每次 metrics／HTTP 收取時間另存 observation。沒有 cron、launchd 或背景定時擷取。

每組詞的真正新增樣本為「本查詢唯一 ID 中，通過平台／原始貼文／品牌相關性／時間品質條件，且不在所有已取得 ID 中的集合」。舊 ID 重新分類另計，人工確認與待審再分列。不能把這次單一全聯查詢新增 17 個 ID／10 個品牌候選，外推成每個新關鍵字都能提供相同增益。

本輪執行狀態：{stage_result['status']}；新的 Threads HTTP 請求 {stage_result['http_request_count']} 次。既有第二批是使用者已取得的資料，沒有冒充本輪自動搜尋。工具 package=0.1.1，但 src/index.js 導出的 VERSION=0.1.0；以固定 Git SHA＋核心檔案雜湊校驗。所有查詢獨立保存 JSON、stdout/stderr、起訖、Exit Code、HTTP journal 與回應；不繼承 Cookie、Token、Proxy。

## 模型可行性與權限

Model A：目前 {s['brand_candidate_count']} 篇待審品牌候選、人工確認 {s['human_confirmed_brand_count']} 篇。議題 {s['provisional_topics']}；暫定情緒 {s['provisional_sentiments']}，皆非 Ground Truth。可做標註試行，不能驗證 100／300／500 篇的取得能力或分類成效；熱門排序、廣告／圖文與多品牌情緒對象仍有偏差。

Model B：確認事件 {s['confirmed_events']}、真實回覆 {s['actual_reply_record_count']}；品牌候選在 {s['span_hours']} 小時跨度只有 {s['observed_publication_hours']} 小時有樣本，其餘是未觀測，不能補成全平台零聲量。共保存 {s['observation_count']} 筆觀測，其中 {s['source_window_observations']} 筆只有 CLI 蒐集區間；具兩個精確觀測時刻的貼文 {s['records_with_two_exact_observation_times']}。欠缺連續時序、事件前後與正常時段對照，不能驗證未來 6／12 小時升溫。回溯模型不得使用事後累積互動；跨事件須按完整事件分組。

目前沒有已確認可直接使用的 Threads 公開資料管道：官方 App 的核准證據與環境 Token 未提供；MCL 顯示 Threads UI 可申請，但本地程式／原始匯出權限另需確認；資料服務 Key／契約及含全聯的公開授權資料包亦未提供。

具體下一步：

1. 在 [Meta App Dashboard](https://developers.facebook.com/apps/) 核對 Threads App、threads_keyword_search 公開搜尋正式核准與用途；先前自己的帳號存取不等於全站公開搜尋。官方 API 核准也不自動授權本非官方工具，應改接相應官方 adapter。
2. 與教授經 [Meta Research Tools Manager](https://www.facebook.com/research-tools-manager) 申請 MCL，確認碩士資格、Threads 歷史／回覆、匯出及模型用途。[SOMAR 官方範圍](https://www.icpsr.umich.edu/sites/somar/meta-content-library)目前把 Threads 列於 UI。
3. 或向 [LargitData](https://www.largitdata.com/社群媒體API/) 申請學術試用，先確認來源權利、模型與論文使用、保存規則及費用；其服務使用爬蟲，付費不自動等於平台授權。

拿到涵蓋方法的有效許可、Stage A 實測與人工品質驗收，才可進入中型實驗。執行程式、GitHub 可連線與合法資料取得是分開的條件。
'''


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['run','analyze','plan','check'],nargs='?',default='run')
    ap.add_argument('--config',type=Path,default=ROOT/'config/experiment.json')
    ap.add_argument('--stage',choices=['A','B','C','context'])
    ap.add_argument('--live',action='store_true')
    ap.add_argument('--skip-github-check',action='store_true')
    ap.add_argument('--approval-context',choices=['default','codex-approved'],default='default',help='Execution-context label only; does not grant any permission')
    args=ap.parse_args(argv)
    root=args.config.resolve().parents[1];cfg=configuration(args.config)
    # Finder need not inherit the user's interactive nvm shell configuration.
    os.environ['PATH']=str(Path(cfg['tool']['node_binary']).parent)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin')
    stamp=datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y%m%d_%H%M%S')
    execution='experiment_'+stamp+'_'+uuid.uuid4().hex[:8]
    directory=root/'runs'/execution;directory.mkdir(parents=True)
    environment=environment_audit(root,network=not args.skip_github_check,tool=cfg['tool'],approval_context=args.approval_context)
    write_json(directory/'environment.json',environment)
    write_json(root/'data/environment_latest.json',environment)
    if args.action=='check':
        print(json.dumps(environment,ensure_ascii=False,indent=2));return 0
    review=load_json(root/'config/relevance_review.json')
    db=connect(root/'data/experiment.sqlite')
    merged=import_existing(cfg,root,db,review)
    reassessed=refresh_assessments(db,review)
    analysis={'two_batch_validation':merged,'dataset':dataset_summary(db),'analyzed_at_utc':utc_now(),
              'source_authorization_status':cfg['authorization']['status'],'changed_relevance_assessments':reassessed,
              'experiment_conditions':{'stages':cfg['stages'],'stopping':cfg['stopping']}}
    write_json(directory/'existing_data_analysis.json',analysis)
    write_json(root/'data/analysis_latest.json',analysis)
    plans={name:planned_stage(cfg,root,name,db) for name in ('A','B','C','context')}
    write_json(directory/'stage_plans.json',plans)
    stage=args.stage or cfg['default_stage']
    if (args.live or cfg['default_mode']=='live') and args.action=='run':
        stage_result=run_live_stage(cfg,args.config,root,db,review,plans[stage],execution,directory)
        analysis['dataset']=dataset_summary(db)
    else:
        stage_result={'status':'DESIGN_ONLY' if stage=='C' else plans[stage]['status'] if plans[stage]['status']!='READY' else 'DRY_RUN',
                      'http_request_count':0,'query_results':[],'network_executed':False}
        for item in plans[stage].get('queries',[]):query_log(db,execution,stage,item,{'status':stage_result['status'],'http_request_count':0,'network_executed':False,'exit_code':None})
    write_json(directory/'stage_result.json',stage_result)
    analysis['stage_result']={k:v for k,v in stage_result.items() if k!='query_results'}
    with db:db.execute('INSERT INTO stage_results VALUES (?,?,?,?,?)',(execution,stage,stage_result['status'],str(directory/'stage_result.json'),utc_now()))
    write_json(root/'data/analysis_latest.json',analysis)
    summary=render_summary(analysis,plans,stage_result,environment)
    (directory/'result_summary.md').write_text(summary,encoding='utf-8')
    (root/'result_summary.md').write_text(summary,encoding='utf-8')
    db.close()
    print(json.dumps(dict(status=stage_result['status'],summary=str(root/'result_summary.md'),
        raw_candidate_ids=analysis['dataset']['unique_candidate_ids'],brand_candidates=analysis['dataset']['brand_candidate_count'],
        human_confirmed=analysis['dataset']['human_confirmed_brand_count'],threads_http_requests=stage_result['http_request_count'],run_directory=str(directory)),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
