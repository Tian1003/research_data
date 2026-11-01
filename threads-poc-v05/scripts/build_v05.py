#!/usr/bin/env python3
"""Extend the v0.4 bundle, preserving raw payloads, IDs and human annotations."""
import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import timedelta, datetime
from pathlib import Path

from core import TW, METRICS, MANUAL_FIELDS, normalize, snapshot, merge_records, apply_reviews, parse_time, utc_now
from reviews import refuse_unimported_edits
from xlsx_io import tabular

ROOT = Path(__file__).resolve().parents[1]


def stats(records, runs, started):
    posts = [r for r in records if r['content_type'] == 'post' and r['brand_relevance'] in ('direct', 'related')]
    replies = [r for r in records if r['content_type'] == 'reply']
    new_posts = [r for r in posts if r['data_origin'] == 'new']
    valid = [r for r in posts if parse_time(r['published_at_utc']) and parse_time(r['published_at_utc']) <= started]
    def recency(rs):
        return {label: sum(started-timedelta(hours=hours) <= parse_time(r['published_at_utc']) <= started
                           for r in rs if parse_time(r['published_at_utc']))
                for label, hours in [('12h',12), ('24h',24), ('7d',168), ('30d',720)]}
    hours = defaultdict(list)
    for r in valid:
        hours[parse_time(r['published_at_utc']).replace(minute=0, second=0, microsecond=0).isoformat()].append(r)
    series = []
    for h, entries in sorted(hours.items()):
        scores = [r['heat_score'] for r in entries if r['heat_score'] is not None]
        nreply = sum(parse_time(r['published_at_utc']) is not None and parse_time(r['published_at_utc']).replace(minute=0, second=0, microsecond=0).isoformat() == h for r in replies)
        series.append(dict(hour_utc=h, observed_post_sample_count=len(entries), observed_reply_record_count=nreply,
                           median_observed_heat_score=statistics.median(scores) if scores else None,
                           metrics_are_later_cumulative_snapshots=True))
    span = int((parse_time(max(hours))-parse_time(min(hours))).total_seconds()/3600)+1 if hours else 0
    vals = dict(total_unique_posts=len(posts), legacy_posts=len(posts)-len(new_posts), new_unique_posts=len(new_posts),
                search_request_count=sum(r.get('network_executed',False) and r.get('collection_method') == 'keyword_search' for r in runs),
                data_http_request_count=sum(bool(r.get('network_executed')) for r in runs),
                live_returned_post_rows=sum((r.get('result_count') or 0) for r in runs if r.get('network_executed') and r.get('collection_method') == 'keyword_search'),
                existing_by_publication_time=recency(posts), newly_fetched_by_publication_time=recency(new_posts),
                reference_at_utc=started.isoformat(), reference_at_tw=started.astimezone(TW).isoformat(),
                observed_reply_records=len(replies), displayed_reply_count_sum=sum(r['reply_count'] for r in posts if r['reply_count'] is not None),
                reply_text_ratio=sum(bool(r['text']) for r in replies)/len(replies) if replies else None,
                reply_timestamp_ratio=sum(bool(r['published_at_utc']) for r in replies)/len(replies) if replies else None,
                reply_confirmed_parent_ratio=sum(bool(r['parent_content_id']) for r in replies)/len(replies) if replies else None,
                review_required_count=sum(r['review_required'] for r in posts), review_priority=dict(Counter(r['review_priority'] for r in posts)),
                review_status=dict(Counter(r['review_status'] for r in posts)),
                manually_confirmed_count=sum(r['review_status'] in ('confirmed','corrected') for r in posts),
                provisional_topics=dict(Counter(r['topic_category'] for r in posts)), provisional_sentiments=dict(Counter(r['sentiment'] for r in posts)),
                text_length=dict(min=min((len(r['text'] or '') for r in posts),default=0), median=statistics.median(len(r['text'] or '') for r in posts) if posts else None,max=max((len(r['text'] or '') for r in posts),default=0)),
                with_media=sum(bool(r['media_hosts']) for r in posts), multi_brand_count=sum(any('多品牌' in x for x in r['review_reasons']) for r in posts),
                actual_fetched_time_known=sum(r['actual_fetched_at_utc'] is not None for r in posts),
                latest_existing_post=max((r['published_at_tw'] for r in valid),default=None),
                distinct_publication_dates=len({r['published_at_tw'][:10] for r in valid}),
                hourly_series=series, occupied_hours=len(hours), publication_span_hours=span,
                hours_without_observed_records=max(0,span-len(hours)), hours_without_records_are_missing_not_zero_volume=True,
                confirmed_events=len({r['event_id'] for r in posts if r['event_id']}),
                missing_fields={k:sum(r.get(k) is None for r in posts) for k in ('text','published_at_utc','source_url','actual_fetched_at_utc',*METRICS)})
    return vals


def migrate_legacy_reviews(records, old, workbook):
    prior = {r['record_id']:r for r in old['normalized_records']}
    by_url = {r['source_url']:r for r in records}
    for r in records:
        if r['record_id'] in prior:
            p = prior[r['record_id']]
            r['previous_system_classification_v04'] = {k:p.get(k) for k in ('topic_category','sentiment','review_reasons','review_status')}
            for new, prev in [('manual_topic','manual_topic_category'),('manual_sentiment','manual_sentiment'),('manual_note','manual_note')]:
                if p.get(prev) is not None:
                    r[new] = p[prev]
    migration = []
    if workbook.exists():
        for row in tabular(workbook,'全聯輿情分析'):
            label, note = row.get('人工判定'), row.get('人工備註')
            if label is None and note is None:
                continue
            r = by_url.get(row.get('原始網址'))
            if r is None:
                raise ValueError('cannot map existing v04 manual annotation by unique URL')
            # Preserve free text exactly. Old column did not encode separate topic/sentiment.
            r['manual_note'] = '\n'.join(str(x) for x in (r.get('manual_note'),label,note) if x is not None)
            migration.append(dict(record_id=r['record_id'], previous_manual_judgment=label, previous_manual_note=note, mapping='unique_source_url_to_v04_record_id'))
    return migration


def build(legacy_path, input_path, root=ROOT, extra_responses=()):
    config = json.loads((root/'config/run.json').read_text())
    sources = json.loads((root/'config/sources.json').read_text())
    started = parse_time(config['run_started_at_utc'])
    old = json.loads(legacy_path.read_text())
    original_bytes = input_path.read_bytes()
    original = json.loads(original_bytes)
    if original != old['raw_responses'][0]['response']:
        raise ValueError('original JSON differs from v04 archived payload; preserve both and inspect before import')
    sha = hashlib.sha256(original_bytes).hexdigest()
    if sha != old['raw_responses'][0]['sha256']:
        raise ValueError('original bytes hash changed from v04')
    if not isinstance(original.get('results'),list) or original.get('status') != 'ok':
        raise ValueError('legacy input is not a successful search payload')
    oldrun = dict(run_id='legacy_quanlian_'+sha[:12], collector='ckelepel-threads', collector_version=None,
                  reported_version_in_v04='0.1.1', collector_version_evidence='legacy file does not record exact executed version',
                  collection_method='keyword_search', data_origin='legacy', raw_response_id='raw_legacy_quanlian',
                  result_path='results', search_keywords=[original.get('query')], request_started_at=None,
                  response_received_at=None, status='LEGACY_IMPORT', result_count=len(original['results']),network_executed=False)
    runs = [oldrun]
    raw_responses = [dict(raw_response_id=oldrun['raw_response_id'], source_path=str(input_path.resolve()),
                         sha256=sha, raw_utf8=original_bytes.decode('utf-8'), response=original, data_origin='legacy')]
    processed = utc_now()
    records = []
    invalid = []
    for i,r in enumerate(original['results']):
        try:
            records.append(normalize(r, oldrun, i, processed))
        except ValueError as e:
            invalid.append(dict(raw_source_ref=f'raw_legacy_quanlian#/response/results/{i}',error=str(e)))
    for path in extra_responses:
        envelope = json.loads(path.read_text())
        run = envelope['run']
        # Only independently recorded executed requests can contribute new observations.
        if not run.get('network_executed') or not run.get('request_started_at') or run.get('status') not in ('SUCCESS','EMPTY','FAILED'):
            raise ValueError('additional response lacks an executed, timestamped collection run')
        response = envelope['response']
        run.update(data_origin='new', raw_response_id=run['run_id'], result_path='data')
        runs.append(run)
        raw_responses.append(dict(raw_response_id=run['run_id'],response=response,raw_utf8=envelope.get('raw_utf8'),data_origin='new'))
        if run['status']=='FAILED':
            continue
        if not run.get('response_received_at') or 'error' in response or not isinstance(response.get('data'),list):
            raise ValueError('successful response lacks received time or valid official data shape')
        for i,item in enumerate(response['data']):
            records.append(normalize(item,run,i,processed))
    snapshots = list({s['snapshot_id']:s for s in map(snapshot,records)}.values())
    unique = merge_records(records)
    migration = migrate_legacy_reviews(unique, old, legacy_path.with_name('threads_analysis_v04.xlsx'))
    state_path = root/'internal/annotations.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'annotations':{},'history':[]}
    apply_reviews(unique,state)
    refuse_unimported_edits(root/'output/threads_analysis_v05.xlsx',unique)
    completed = utc_now()
    for tool in ('ckelepel-threads','threads-content-research-agent','Meta Threads API'):
        runs.append(dict(run_id='v05_not_executed_'+tool, collector=tool,
                         collection_method='keyword_search', status='BLOCKED',
                         block_reason='使用者確認尚無正式核准的公開搜尋權限或授權資料來源',
                         search_keywords=config['keywords'], request_started_at=None, response_received_at=None,
                         result_count=None, network_executed=False))
    summary = stats(unique,runs,started)
    validations = dict(P1={'status':'NOT_TESTED','evidence':'等待 XLSX 日期底層數值的重新讀檔驗證'},
                       P2={'status':'PARTIAL','evidence':'已加情緒對象、反諷複核與有歷史的人工匯入；尚無人工真值標註'},
                       P3={'status':'PARTIAL','evidence':'已查核五種管道並提供有界官方 API 測試程式；目前沒有已核准可連線來源'},
                       P4={'status':'BLOCKED','evidence':'兩套固定版本原始碼已比較；尚未進行獲授權的新搜尋與有效分頁實測'},
                       P5={'status':'BLOCKED','evidence':'尚無適用的回覆存取授權；工具輸出的父節點／時間可能是推定值'},
                       P6={'status':'BLOCKED','evidence':'新增品牌樣本為零；缺少人工標註、確認事件與連續觀測'})
    bundle = dict(schema_version='0.4', extensions_version='0.5',
        processing_run=dict(run_id='v05_'+started.strftime('%Y%m%dT%H%M%SZ'),started_at_utc=started.isoformat(),completed_at_utc=completed,
                            timezone='Asia/Taipei', kind='legacy_import_and_source_feasibility_audit'),
        authorization=dict(status='not_approved', evidence=config['authorization_evidence'],
                           approved_public_search_permissions=[], environment_token_configured=False),
        collection_plan=config['bounded_test'], collection_runs=runs, raw_responses=raw_responses,
        normalized_records=unique, interaction_snapshots=snapshots, actual_reply_records=[r for r in unique if r['content_type']=='reply'],
        annotation_history=state['history'], legacy_annotation_migration=migration,
        source_assessment=sources, validation=dict(problems=validations,statistics=summary,
        invalid_records=invalid, legacy_snapshot_time_unknown=sum(s['observed_at_utc'] is None for s in snapshots),
        raw_count=len(original['results']), duplicate_rows_removed=len(records)-len(unique),
        original_file_sha256=sha, old_v04_file_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_path.parent.iterdir() if p.is_file()},
        limitations=['legacy collector may have substituted missing metric values with zero; cannot reverse from export',
                     'legacy fetch time unknown; snapshots with NULL time cannot estimate growth',
                     'publication-time counts are obtained samples, not a platform census',
                     'source documentation downloads and GitHub code reads are not Threads searches'],
        errors=[{'type':'DOCS_RATE_LIMIT','source':'Meta developers / transparency docs','status':429,'action':'stopped; used official Meta Postman and SOMAR pages'},
                {'type':'TOOL_B_ENVIRONMENT','local_go':'1.19','required_go':'>=1.26','action':'source reviewed; not built; existing Go/Node environment unchanged'}]))
    out = root/'output'
    out.mkdir(parents=True,exist_ok=True)
    (out/'threads_raw_v05.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
    return bundle


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--legacy',type=Path,default=ROOT.parent/'threads-poc-v04/output/threads_raw_v04.json')
    ap.add_argument('--input',type=Path,default=ROOT.parent/'quanlian.json')
    ap.add_argument('--response',type=Path,action='append',default=[])
    a=ap.parse_args()
    x=build(a.legacy,a.input,extra_responses=a.response)
    print(json.dumps({k:x['validation']['statistics'][k] for k in ('total_unique_posts','new_unique_posts','search_request_count','existing_by_publication_time','reference_at_tw')},ensure_ascii=False,indent=2))
