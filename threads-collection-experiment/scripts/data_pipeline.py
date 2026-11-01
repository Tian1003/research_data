"""Offline import, incremental yield and snapshot storage, using the v0.5 canonical adapter."""
import copy
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'threads-poc-v05/scripts'))
from core import normalize, parse_time, utc_now, source_platform, METRICS


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate_payload(doc):
    errors=[]
    if not isinstance(doc,dict) or doc.get('status')!='ok' or not isinstance(doc.get('results'),list):
        return ['expected status=ok with a results array']
    if type(doc.get('count')) is not int or doc['count']!=len(doc['results']):
        errors.append('declared_count_mismatch')
    for i,p in enumerate(doc['results']):
        if not isinstance(p,dict) or not isinstance(p.get('id'),(str,int)) or isinstance(p.get('id'),bool) or not re.fullmatch(r'\d+',str(p['id'])):
            errors.append(f'invalid_id_at_{i}')
    return errors


def assess(raw,review):
    text=raw.get('caption') or ''
    override=review.get('overrides',{}).get(str(raw['id']))
    if override:
        return copy.deepcopy(override)
    brand='全聯' in text or re.search(r'\bpxmart\b',text,re.I)
    if not brand:
        return {'brand_relevance':'context_only' if any(k in text for k in ('超市','量販店')) else 'uncertain', 'reason':'尚無文字證據明確指向全聯', 'sentiment_target':'unknown'}
    if any(k in text for k in ('店前','門口','蹲在','集合地點')) and any(k in text for k in ('唱歌','發飄帶','集合','邀約')):
        return {'brand_relevance':'context_only','reason':'品牌主要作為集合地點','sentiment_target':'活動／地點'}
    consumer_terms=('買','商品','價','特惠','促銷','新品','雞湯','蝦仁','牛奶','優格','藍莓','蛋餅','台灣鯛','洗衣精','餅乾','半月燒','花枝漿','鍋','wifi','客服','服務','小時達','門市','便當','牙膏','洋蔥','銅鑼燒','染髮劑','印花','集點','換購','兌換')
    if any(k in text.lower() for k in consumer_terms):
        return {'brand_relevance':'direct','reason':'文字可辨識為全聯商品、價格、服務或官方資訊；尚待人工確認'}
    return {'brand_relevance':'uncertain','reason':'品牌文字命中，但缺少足夠商品／服務／品牌議題脈絡','sentiment_target':'unknown'}


def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY,input_path TEXT NOT NULL,sha256 TEXT NOT NULL,origin TEXT NOT NULL,start_utc TEXT,finish_utc TEXT,metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS records(record_id TEXT PRIMARY KEY,platform_content_id TEXT NOT NULL,source_platform TEXT NOT NULL,brand_relevance TEXT NOT NULL,canonical_json TEXT NOT NULL,UNIQUE(source_platform,platform_content_id));
    CREATE TABLE IF NOT EXISTS observations(snapshot_id TEXT PRIMARY KEY,record_id TEXT NOT NULL REFERENCES records(record_id),source_id TEXT NOT NULL REFERENCES sources(source_id),observed_at_utc TEXT,window_start_utc TEXT,window_end_utc TEXT,time_basis TEXT NOT NULL,like_count INTEGER,reply_count INTEGER,repost_count INTEGER,quote_count INTEGER,raw_source_ref TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_records(source_id TEXT REFERENCES sources(source_id),record_id TEXT REFERENCES records(record_id),PRIMARY KEY(source_id,record_id));
    CREATE TABLE IF NOT EXISTS query_runs(run_id TEXT PRIMARY KEY,stage TEXT NOT NULL,keyword TEXT,started_utc TEXT,finished_utc TEXT,status TEXT NOT NULL,exit_code INTEGER,http_request_count INTEGER NOT NULL,raw_path TEXT,report_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS stage_results(execution_id TEXT PRIMARY KEY,stage TEXT NOT NULL,status TEXT NOT NULL,report_path TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS relevance_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,processed_at TEXT NOT NULL);
    ''')
    return db


def known_ids(db,brand_only=False):
    q='SELECT record_id FROM records'+(" WHERE brand_relevance IN ('direct','related')" if brand_only else '')
    return {r[0] for r in db.execute(q)}


def batch_metrics(doc,review,baseline_ids,baseline_brand_ids,reference):
    errors=validate_payload(doc)
    if errors:
        return {'status':'INVALID_JSON_STRUCTURE','errors':errors}
    unique={str(p['id']):p for p in doc['results']}
    identifiers={f'{source_platform(p.get("url"))}:{"reply" if p.get("is_reply") else "post"}:{pid}' for pid,p in unique.items()}
    direct=set();related=set();uncertain=set();context=set();rows=[]
    age_counts={k:0 for k in ('12h','24h','7d','30d')}
    brand_age=dict(age_counts);direct_age=dict(age_counts)
    invalid_time=0
    for pid,p in unique.items():
        rid=f'{source_platform(p.get("url"))}:{"reply" if p.get("is_reply") else "post"}:{pid}'
        a=assess(p,review);group=a['brand_relevance']
        eligible=source_platform(p.get('url'))=='threads' and not p.get('is_reply')
        bucket=direct if group=='direct' else related if group=='related' else context if group=='context_only' else uncertain
        bucket.add(rid)
        published=parse_time(p.get('taken_at'))
        if published is None or published>reference:
            invalid_time+=1
        else:
            for label,h in [('12h',12),('24h',24),('7d',168),('30d',720)]:
                inside=reference-timedelta(hours=h)<=published<=reference
                age_counts[label]+=int(inside)
                brand_age[label]+=int(inside and eligible and group in ('direct','related'))
                direct_age[label]+=int(inside and eligible and group=='direct')
        rows.append(dict(record_id=rid,brand_relevance=group,reason=a['reason'],new_id=rid not in baseline_ids,
                         brand_candidate=eligible and group in ('direct','related') and published is not None and published<=reference,human_confirmed=False,
                         text=p.get('caption'),source_url=p.get('url'),published_at_utc=published.isoformat() if published else None))
    brand={r['record_id'] for r in rows if r['brand_candidate']}
    newly_brand=brand-baseline_brand_ids
    return dict(status='VALID_EMPTY' if not unique else 'VALID',raw_rows=len(doc['results']),unique_ids=len(unique),
                duplicates_within_batch=len(doc['results'])-len(unique),cross_batch_duplicate_ids=sorted(identifiers&baseline_ids),
                cross_batch_duplicate_count=len(identifiers&baseline_ids),duplicate_rate=len(identifiers&baseline_ids)/len(identifiers) if identifiers else None,
                new_ids=sorted(identifiers-baseline_ids),new_id_count=len(identifiers-baseline_ids),
                relevance_counts=dict(direct=len(direct),related=len(related),context_only=len(context),uncertain=len(uncertain)),
                brand_candidate_count=len(brand),new_brand_candidate_ids=sorted(newly_brand),new_brand_candidate_count=len(newly_brand),
                newly_retrieved_brand_ids=sorted((identifiers-baseline_ids)&brand),newly_retrieved_brand_count=len((identifiers-baseline_ids)&brand),
                reclassified_existing_brand_ids=sorted(newly_brand&baseline_ids),human_confirmed_count=0,
                published_time_counts=age_counts,brand_candidate_time_counts=brand_age,direct_time_counts=direct_age,
                missing_or_future_timestamp_count=invalid_time,reference_at_utc=reference.isoformat(),
                review_pending_rows=rows)


def ingest(db,doc,source,review,previous_records=None):
    errors=validate_payload(doc)
    if errors:
        raise ValueError(str(errors))
    source_id=source['source_id']
    if db.execute('SELECT 1 FROM sources WHERE source_id=?',(source_id,)).fetchone():
        return False
    before=known_ids(db);brand_before=known_ids(db,True)
    reference=parse_time(source.get('start_utc') or source.get('reference_utc'))
    summary=batch_metrics(doc,review,before,brand_before,reference)
    meta={**source,'ingest_metrics':summary}
    with db:
        db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)',(source_id,source['input_path'],source['sha256'],source['origin'],source.get('start_utc'),source.get('finish_utc'),json.dumps(meta,ensure_ascii=False)))
        for i,raw in enumerate(doc['results']):
            run=dict(collector='ckelepel-threads',collector_version=source.get('collector_version'),
                     collection_method='keyword_search',run_id=source_id,raw_response_id=source_id,result_path='results',
                     search_keywords=[doc.get('query')],data_origin='legacy' if source['origin']=='legacy' else source['origin'],
                     response_received_at=source.get('exact_received_at_utc'))
            r=normalize(raw,run,i,utc_now())
            observations=[o for o in source.get('per_post_observations',[]) if str(o['id'])==str(raw['id'])]
            matches=[o for o in observations if all(o.get(k)==r[k] for k in METRICS) and o.get('text')==r['text']]
            received=min((o['response_received_at'] for o in matches),default=source.get('exact_received_at_utc'))
            a=assess(raw,review)
            r['brand_relevance']=a['brand_relevance']
            r['experimental_relevance_assessment']={**a,'human_confirmed':False,'criterion_version':review['criterion_version']}
            r['review_reasons'].append(a['reason'])
            if 'sentiment_target' in a:
                r['sentiment_target']=a['sentiment_target']
                r['sentiment']='uncertain' if a['brand_relevance'] in ('context_only','uncertain','related') else r['sentiment']
                r['crisis_candidate']='uncertain'
            r['actual_fetched_at_utc']=received
            r['observation_time_evidence']='matching_metrics_and_text_in_instrumented_HTTP_response' if matches else source['time_basis']
            r['recorded_collection_window']={'start_utc':source.get('start_utc'),'finish_utc':source.get('finish_utc'),'basis':source['time_basis']}
            r['brand']='全聯' if r['brand_relevance'] in ('direct','related') else None
            r['experimental_eligible_brand_candidate']=any(x['record_id']==r['record_id'] and x['brand_candidate'] for x in summary['review_pending_rows'])
            existing=db.execute('SELECT canonical_json FROM records WHERE record_id=?',(r['record_id'],)).fetchone()
            previous=json.loads(existing[0]) if existing else (previous_records or {}).get(r['record_id'],{})
            # Explicit manual data always survives automated ingestion.
            for k,v in previous.items():
                if k.startswith('manual_') or k in ('event_id','review_status'):
                    if v is not None:
                        r[k]=v
            refs=previous.get('raw_source_refs',[])+r['raw_source_refs']
            r['raw_source_refs']=list(dict.fromkeys(refs))
            r['search_keywords']=list(dict.fromkeys(previous.get('search_keywords',[])+r['search_keywords']))
            r['review_required']=r.get('review_status') not in ('confirmed','corrected')
            db.execute('INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET brand_relevance=excluded.brand_relevance,canonical_json=excluded.canonical_json',
                       (r['record_id'],r['platform_content_id'],r['source_platform'],r['brand_relevance'],json.dumps(r,ensure_ascii=False)))
            db.execute('INSERT OR IGNORE INTO source_records VALUES (?,?)',(source_id,r['record_id']))
            # Keep all separate HTTP snapshots, not just the SDK's first chosen version.
            if observations:
                for o in observations:
                    snap_id=sha((source_id+'|'+str(o['request_id'])+'|'+r['record_id']).encode())
                    db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (snap_id,r['record_id'],source_id,o['response_received_at'],o['request_started_at'],o['response_received_at'],
                        'instrumented_http_response_receipt',*(o.get(k) for k in METRICS),o['raw_http_ref']))
            else:
                snap_id=sha((source_id+'|'+str(i)+'|'+r['record_id']).encode())
                # Supplied outer CLI finish is an upper bound; never invent an exact response time.
                db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (snap_id,r['record_id'],source_id,source.get('exact_received_at_utc'),source.get('start_utc'),source.get('finish_utc'),source['time_basis'],*(r[k] for k in METRICS),r['raw_source_ref']))
    return True


def records(db):
    return [json.loads(r[0]) for r in db.execute('SELECT canonical_json FROM records ORDER BY record_id')]


def refresh_assessments(db,review):
    """Reassess derived relevance without touching raw responses, snapshots or manual labels."""
    changed=0
    with db:
        for r in records(db):
            a=assess({'id':r['platform_content_id'],'caption':r['text']},review)
            before=r.get('experimental_relevance_assessment',{})
            after={**a,'human_confirmed':False,'criterion_version':review['criterion_version']}
            source_row=db.execute('SELECT metadata_json FROM sources WHERE source_id=?',(r['run_id'],)).fetchone()
            source=json.loads(source_row[0]) if source_row else {}
            reference=source.get('start_utc') or source.get('reference_utc')
            published=parse_time(r['published_at_utc']);ref=parse_time(reference)
            eligible=a['brand_relevance'] in ('direct','related') and r['source_platform']=='threads' and r['content_type']=='post' and published is not None and ref is not None and published<=ref
            if before==after and r.get('experimental_eligible_brand_candidate')==eligible and r.get('eligibility_reference_utc')==reference:
                continue
            db.execute('INSERT INTO relevance_history(record_id,before_json,after_json,processed_at) VALUES (?,?,?,?)',
                       (r['record_id'],json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),utc_now()))
            r['experimental_relevance_assessment']=after
            r['brand_relevance']=a['brand_relevance']
            r['brand']='全聯' if a['brand_relevance'] in ('direct','related') else None
            r['review_reasons']=[x for x in r['review_reasons'] if x!=before.get('reason')]+[a['reason']]
            if 'sentiment_target' in a:
                r['sentiment_target']=a['sentiment_target']
                r['sentiment']='uncertain'
                r['crisis_candidate']='uncertain'
            else:
                from core import classify
                initial=classify(r['text'],bool(r.get('media_hosts')))
                for field in ('sentiment','sentiment_target','crisis_candidate'):
                    r[field]=initial[field]
            r['experimental_eligible_brand_candidate']=eligible
            r['eligibility_reference_utc']=reference
            db.execute('UPDATE records SET brand_relevance=?,canonical_json=? WHERE record_id=?',(r['brand_relevance'],json.dumps(r,ensure_ascii=False),r['record_id']))
            changed+=1
    return changed


def dataset_summary(db):
    rows=records(db)
    core=[r for r in rows if r['content_type']=='post' and r['source_platform']=='threads' and r['brand_relevance'] in ('direct','related') and r.get('experimental_eligible_brand_candidate')]
    hours=Counter(parse_time(r['published_at_utc']).replace(minute=0,second=0,microsecond=0).isoformat() for r in core if parse_time(r['published_at_utc']))
    span=int((parse_time(max(hours))-parse_time(min(hours))).total_seconds()/3600)+1 if hours else 0
    known_points=db.execute('SELECT COUNT(*) FROM observations WHERE observed_at_utc IS NOT NULL').fetchone()[0]
    speed_eligible=db.execute('SELECT COUNT(*) FROM (SELECT record_id FROM observations WHERE observed_at_utc IS NOT NULL GROUP BY record_id HAVING COUNT(DISTINCT observed_at_utc)>=2)').fetchone()[0]
    human_complete=[r for r in core if r['review_status'] in ('confirmed','corrected') and
                    all(r.get(k) is not None for k in ('manual_topic','manual_sentiment','manual_sentiment_target','manual_crisis_candidate'))]
    return dict(unique_candidate_ids=len(rows),relevance_counts=dict(Counter(r['brand_relevance'] for r in rows)),
                brand_candidate_count=len(core),direct_brand_candidate_count=sum(r['brand_relevance']=='direct' for r in core),
                pending_human_brand_candidates=sum(r['review_status']=='pending' for r in core),
                human_confirmed_brand_count=len(human_complete),
                provisional_topics=dict(Counter(r['topic_category'] for r in core)),
                provisional_sentiments=dict(Counter(r['sentiment'] for r in core)),
                distinct_publication_dates=len({r['published_at_tw'][:10] for r in core if r['published_at_tw']}),
                source_count=db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],
                observation_count=db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
                exact_observation_timestamps=known_points,records_with_two_exact_observation_times=speed_eligible,
                source_window_observations=db.execute('SELECT COUNT(*) FROM observations WHERE window_start_utc IS NOT NULL AND observed_at_utc IS NULL').fetchone()[0],
                confirmed_events=len({r['event_id'] for r in core if r.get('event_id')}),
                actual_reply_record_count=sum(r['content_type']=='reply' for r in rows),
                observed_publication_hours=len(hours),span_hours=span,unobserved_hours=max(0,span-len(hours)),
                hourly_observed_brand_candidate_counts=dict(sorted(hours.items())),
                platform_census=False)
