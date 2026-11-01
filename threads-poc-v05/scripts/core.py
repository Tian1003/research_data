"""Canonical Schema 0.4 with additive PoC 0.5 fields. No network I/O."""
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

UTC = timezone.utc
TW = ZoneInfo('Asia/Taipei')
METRICS = ('like_count', 'reply_count', 'repost_count', 'quote_count')
MANUAL_FIELDS = ('manual_topic', 'manual_sentiment', 'manual_sentiment_target',
                 'manual_crisis_candidate', 'manual_note', 'review_status')
TOPICS = ('商品體驗', '商品品質', '價格與促銷', '門市服務', '品牌爭議', '其他', '待判定')
SENTIMENTS = ('positive', 'negative', 'neutral', 'mixed', 'uncertain')
CRISES = ('yes', 'no', 'uncertain')


def utc_now():
    return datetime.now(UTC).isoformat()


def parse_time(value):
    """Accept Unix seconds/milliseconds or timezone-aware ISO; never guess local TZ."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (float, int)) or re.fullmatch(r'-?\d+(?:\.\d+)?', str(value)):
            seconds = float(value)
            if not math.isfinite(seconds):
                return None
            if abs(seconds) >= 100_000_000_000:
                seconds /= 1000
            d = datetime.fromtimestamp(seconds, UTC)
        else:
            d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if d.tzinfo is None:
                return None
            d = d.astimezone(UTC)
        return d if d.year >= 2000 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def excel_serial(iso_time):
    """Excel has no timezone. Encode Taipei wall-clock, NOT the UTC instant."""
    dt = parse_time(iso_time)
    if dt is None:
        return None
    local = dt.astimezone(TW).replace(tzinfo=None)
    return (local - datetime(1899, 12, 30)).total_seconds() / 86400


def source_platform(url):
    try:
        host = (urlparse(url or '').hostname or '').lower()
    except ValueError:
        return 'unknown'
    return 'threads' if any(host == d or host.endswith('.' + d)
                            for d in ('threads.com', 'threads.net')) else 'unknown'


def media_hosts(raw):
    hosts = set()
    def walk(v):
        if isinstance(v, str) and v.startswith(('https://', 'http://')):
            hosts.add(urlparse(v).hostname)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    # Deliberately excludes user avatars and unrelated author fields.
    walk(raw.get('media', raw.get('media_urls', [])))
    return sorted(x for x in hosts if x)


def metric(raw, name):
    value = raw.get(name)
    aliases = dict(zip(METRICS, ('likes', 'replies', 'reposts', 'quotes')))
    if name not in raw:
        value = (raw.get('metrics') or {}).get(aliases[name])
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def relevance(text):
    if '全聯' in (text or '') or re.search(r'\bpxmart\b', text or '', re.I):
        return 'direct'
    if any(x in (text or '') for x in ('超市', '量販店', '生鮮超市')):
        return 'context_only'
    return 'uncertain'


def classify(text, has_media=False):
    """Conservative brand-target rules; all labels are proposals, never ground truth."""
    t = text or ''
    reasons = []
    topic, sentiment, target, crisis, priority = '待判定', 'uncertain', 'unknown', 'uncertain', 'low'
    brand_hit = relevance(t) == 'direct'
    if brand_hit:
        target = '全聯或其商品'
    others = [b for b in ('好市多', '家樂福', '金色三麥', '萊爾富') if b in t]
    irony = any(w in t for w in ('拜託大家不要去買', '被我抓到最後一盒', '不演了', '還沒被煮很生氣', '裡面要氣爆'))
    if irony:
        reasons.append('可能反諷、擬人玩笑或缺圖片脈絡，不能直接判定品牌爭議')
        priority = 'high'
    elif others and brand_hit:
        # Attribute explicit clauses, not every negative token to the query brand.
        if ('全聯' in t and any(x in t for x in ('很可以', '很好吃', '好吃', '比好市多'))
                and re.search(r'好市多.{0,30}(過敏|蕁麻疹)', t, re.S)):
            topic, sentiment, target, crisis = '商品體驗', 'positive', '全聯商品', 'no'
        reasons.append('多品牌比較；負面過敏／品質敘述不可移轉給全聯')
        priority = 'high'
    else:
        positive = any(x in t for x in ('好吃', '好喝', '漂亮', '方便', '可愛', '給力', '幸運', '推薦'))
        negative = any(x in t for x in ('太貴', '有點貴', '過期', '發霉', '不新鮮', '像漿糊', '抱怨', '投訴', '食物中毒'))
        quality = any(x in t for x in ('過期', '發霉', '不新鮮', '像漿糊', '異物', '食物中毒'))
        if any(x in t for x in ('特價', '折', '點數', '50點', '49元', '有點貴', '價格', '促銷', '有送')):
            topic = '價格與促銷'
        elif any(x in t.lower() for x in ('wifi', '店員', '客服', '服務態度')):
            topic = '門市服務'
        elif quality:
            topic = '商品品質'
        elif any(x in t for x in ('優格', '蝦仁', '牛奶', '雞湯', '便當', '餅乾', '蛋餅', '銅鑼燒', '染髮劑', '藍莓', '魚', '花枝漿', '鍋', '甜點')):
            topic = '商品體驗'
        if positive and negative:
            sentiment, priority = 'mixed', 'medium'
            reasons.append('正負評價並存，需確認轉折與情緒對象')
        elif positive:
            sentiment, crisis = 'positive', 'no'
        elif negative:
            sentiment, priority = 'negative', 'high'
            reasons.append('疑似商品品質／抱怨，尚未確認事件與影響範圍')
            crisis = 'yes' if any(x in t for x in ('食物中毒', '發霉', '異物', '集體投訴')) else 'uncertain'
        # Questions are not endorsements just because they contain "好吃".
        if any(x in t for x in ('好吃嗎', '好吃嗎？', '這是很好吃嗎')):
            sentiment, crisis = 'uncertain', 'uncertain'
            reasons.append('詢問語氣，不直接視為正面推薦')
        if quality:
            priority = 'high'
    if has_media:
        reasons.append('附圖片或影片但尚未檢視，需確認其是否影響語意')
        if priority == 'low':
            priority = 'medium'
    if any(x in t for x in ('業配', '合作', '廣告', '轉貼', '轉發自')):
        reasons.append('疑似廣告、合作或轉貼，尚未確認')
        if priority == 'low':
            priority = 'medium'
    if len(t.strip()) < 25 or topic == '待判定' or sentiment == 'uncertain':
        reasons.append('文字過短或規則無法明確判定')
        if priority == 'low':
            priority = 'medium'
    reasons.append('初期樣本須研究者人工標註；系統提案尚非 Ground Truth')
    return dict(topic_category=topic, sentiment=sentiment, sentiment_target=target,
                crisis_candidate=crisis, review_required=True, review_priority=priority,
                review_reasons=reasons, review_status='pending', classifier_version='v05-target-aware-rules-1')


def normalize(raw, run, index, processed_at):
    tool = run['collector']
    pid = raw.get('id')
    if isinstance(pid, bool) or not isinstance(pid, (str, int)) or not re.fullmatch(r'\d+', str(pid)):
        raise ValueError('missing/invalid platform ID; expected decimal string/integer')
    pid = str(pid)
    url = raw.get('url', raw.get('permalink'))
    text = raw.get('caption') if isinstance(raw.get('caption'), str) else raw.get('text')
    is_reply = bool(raw.get('is_reply')) or run.get('collection_method') == 'replies'
    typ = 'reply' if is_reply else 'post'
    published = parse_time(raw.get('taken_at', raw.get('timestamp')))
    parent = raw.get('reply_to_id')  # only explicit platform-ID evidence
    root = pid if not is_reply else None
    if tool == 'ckelepel-threads' and is_reply:
        # parent_id and created_at can be generated by this collector.
        published = parse_time(raw.get('taken_at'))
        parent = raw.get('parent_id') if raw.get('parent_id_source') == 'platform' else None
        root = raw.get('post_id') if run.get('root_verified') else None
    if tool == 'threads-content-research-agent' and is_reply:
        parent = None  # PostReplies currently substitutes root for all ParentID values.
        root = raw.get('root_id') if run.get('root_verified') else None
    if tool == 'Meta Threads API' and is_reply:
        parent = raw.get('replied_to', {}).get('id') if isinstance(raw.get('replied_to'), dict) else raw.get('reply_to_id')
        root = run.get('verified_root_id')
    fetched = None if run.get('data_origin') == 'legacy' else run.get('response_received_at')
    platform = source_platform(url)
    metrics = {k: metric(raw, k) for k in METRICS}
    ref = f'{run["raw_response_id"]}#/response/{run.get("result_path", "results")}/{index}'
    r = dict(record_id=f'{platform}:{typ}:{pid}', source_platform=platform,
             collector_tool=tool, collector_version=run.get('collector_version'),
             collection_method=run.get('collection_method', 'keyword_search'), run_id=run['run_id'],
             search_keywords=run.get('search_keywords', []), brand='全聯' if relevance(text) == 'direct' else None,
             brand_relevance=relevance(text), event_id=None, content_type=typ,
             platform_content_id=pid, parent_content_id=str(parent) if parent else None,
             root_content_id=str(root) if root else None, source_url=url, text=text,
             published_at_utc=published.isoformat() if published else None,
             published_at_tw=published.astimezone(TW).isoformat() if published else None,
             actual_fetched_at_utc=fetched, processed_at_utc=processed_at,
             raw_source_ref=ref, raw_source_refs=[ref], data_origin=run.get('data_origin', 'new'),
             data_origins=[run.get('data_origin','new')],
             post_url_host=urlparse(url).hostname if url else None, media_hosts=media_hosts(raw),
             source_timestamp_unit='milliseconds' if isinstance(raw.get('taken_at'), (int, float)) and raw['taken_at'] >= 100_000_000_000 else 'seconds' if isinstance(raw.get('taken_at'), (int, float)) else 'ISO_or_missing',
             **metrics, **classify(text, bool(raw.get('has_media') or raw.get('media') or raw.get('media_urls'))))
    r.update({k: None for k in MANUAL_FIELDS if k != 'review_status'})
    r['heat_score'] = sum(metrics[k] * w for k, w in zip(METRICS, (1, 3, 4, 2))) if all(v is not None for v in metrics.values()) else None
    r['publication_time_evidence'] = 'collector_reported; upstream fallback cannot be excluded' if tool == 'ckelepel-threads' else 'source_reported'
    r['linkage_evidence'] = 'explicit_only; collector heuristics discarded'
    r['provenance_observations'] = [dict(run_id=run['run_id'], collector_tool=tool,
        collector_version=run.get('collector_version'), actual_fetched_at_utc=fetched,
        raw_source_ref=ref, search_keywords=run.get('search_keywords', []))]
    return r


def snapshot(record):
    evidence = dict(record_id=record['record_id'], run_id=record['run_id'],
                    observed_at_utc=record['actual_fetched_at_utc'],
                    raw_source_ref=record['raw_source_ref'],
                    **{k: record[k] for k in METRICS})
    evidence['snapshot_id'] = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    evidence['observation_time_status'] = 'known_response_received_at' if evidence['observed_at_utc'] else 'unknown_legacy'
    return evidence


def merge_records(records):
    unique = {}
    for original in records:
        r = copy.deepcopy(original)
        key = (r['source_platform'], r['platform_content_id'])
        if key not in unique:
            unique[key] = r
            continue
        old = unique[key]
        if old['content_type'] != r['content_type']:
            old['review_reasons'].append('來源對 post/reply 類型有衝突')
        old['search_keywords'] = list(dict.fromkeys(old['search_keywords'] + r['search_keywords']))
        old['data_origins'] = list(dict.fromkeys(old['data_origins'] + r['data_origins']))
        old['raw_source_refs'] = list(dict.fromkeys(old['raw_source_refs'] + r['raw_source_refs']))
        old['provenance_observations'] += r['provenance_observations']
        # Keep metrics from latest known observation. Each observation remains in snapshots.
        if r.get('actual_fetched_at_utc') and (not old.get('actual_fetched_at_utc') or r['actual_fetched_at_utc'] > old['actual_fetched_at_utc']):
            for f in (*METRICS, 'actual_fetched_at_utc', 'heat_score'):
                old[f] = r[f]
    return list(unique.values())


def apply_reviews(records, state):
    for r in records:
        saved = state.get('annotations', {}).get(r['record_id'], {})
        for k in MANUAL_FIELDS:
            if k in saved:
                r[k] = saved[k]
    return records
