#!/usr/bin/env python3
import argparse, csv, hashlib, json, math, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TW=ZoneInfo('Asia/Taipei'); UTC=timezone.utc
TOOL='ckelepel-threads'; VERSION='0.1.1'; METHOD='offline-normalization-of-existing-search-json'
CORE=['全聯','全聯福利中心','#全聯','#全聯福利中心','pxmart']
EXT=['全聯小時達','全聯門市','全聯商品']
CONTEXT=['超市','量販店','生鮮超市','#超市','#量販店']

def parse_dt(s): return datetime.fromisoformat(s).astimezone(TW)
def iso(ts,tz=UTC):
    try: return datetime.fromtimestamp(float(ts),UTC).astimezone(tz).isoformat()
    except (TypeError,ValueError,OverflowError): return None
def host(url): return urlparse(url).hostname or None if url else None
def media_hosts(p):
    vals=[]
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if k=='url' and isinstance(v,str):
                    h=host(v)
                    if h and h not in vals: vals.append(h)
                else: walk(v)
        elif isinstance(x,list):
            for y in x: walk(y)
    walk(p.get('media')); walk(p.get('link_preview'))
    return vals
def matching(p):
    text=p.get('caption') or ''
    direct=[k for k in CORE if k.lower() in text.lower()]
    related=[k for k in EXT if k.lower() in text.lower()]
    context=[k for k in CONTEXT if k.lower() in text.lower()]
    if direct: return 'direct_brand',direct+related+context
    if related: return 'brand_related',related+context
    if context: return 'context_only',context
    return 'unknown',[]
def normalize(p, run_started, search_keywords):
    match, hits=matching(p); published=iso(p.get('taken_at')); pubdt=datetime.fromisoformat(published) if published else None
    age=(run_started.astimezone(UTC)-pubdt).total_seconds()/3600 if pubdt else None
    vals=[p.get('like_count'),p.get('reply_count'),p.get('repost_count'),p.get('quote_count')]
    complete=all(isinstance(v,(int,float)) for v in vals)
    heat=(vals[0]+3*vals[1]+4*vals[2]+2*vals[3]) if complete else None
    return {'post_id':str(p['id']) if p.get('id') is not None else None,'published_at_utc':published,'published_at_tw':pubdt.astimezone(TW).isoformat() if pubdt else None,'age_hours':round(age,4) if age is not None else None,'text':p.get('caption'),'match_type':match,'matched_keywords':hits,'like_count':p.get('like_count'),'reply_count':p.get('reply_count'),'repost_count':p.get('repost_count'),'quote_count':p.get('quote_count'),'heat_score':heat,'heat_complete':complete,'source_platform':'Threads','collector_tool':TOOL,'collector_version':VERSION,'retrieval_method':METHOD,'post_url':p.get('url'),'post_url_host':host(p.get('url')),'media_hosts':media_hosts(p),'search_keywords':search_keywords,'collected_at':run_started.isoformat(),'raw_source_file':'quanlian.json','is_reply':p.get('is_reply'),'parent_post_id':None,'root_post_id':str(p['id']) if p.get('id') is not None else None}
def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
def build(inp,root,run_started):
    doc=json.loads(Path(inp).read_text(encoding='utf-8')); search_keywords=[doc.get('query')] if doc.get('query') else []
    raw=json.dumps(doc,ensure_ascii=False,sort_keys=True).encode(); sha=hashlib.sha256(raw).hexdigest()
    rows=[normalize(p,run_started,search_keywords) for p in doc.get('results',[])]
    # The replay window is [run_started-12h, run_started]; no future/missing timestamps qualify.
    lo=run_started-timedelta(hours=12); hi=run_started
    eligible=[r for r in rows if r['published_at_utc'] and lo.astimezone(UTC)<=datetime.fromisoformat(r['published_at_utc'])<=hi.astimezone(UTC) and r['match_type'] in ('direct_brand','brand_related')]
    eligible.sort(key=lambda r:r['published_at_utc'],reverse=True)
    heat=sorted(eligible,key=lambda r:(r['heat_score'] is not None,r['heat_score'] or -math.inf,r['published_at_utc']),reverse=True)
    for i,r in enumerate(heat,1): r['heat_rank']=i
    fields=['post_id','published_at_tw','age_hours','text','match_type','like_count','reply_count','repost_count','quote_count','heat_score','heat_rank','source_platform','collector_tool','post_url']
    out=root/'data/processed'; out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'quanlian_12h_latest.csv',eligible,fields); write_csv(out/'quanlian_12h_heat_ranked.csv',heat,fields)
    with (out/'posts_normalized.jsonl').open('w',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
    context=[r for r in rows if r['match_type']=='context_only']; write_csv(out/'context_posts.csv',context,fields)
    prov={'run_id':'offline_'+run_started.strftime('%Y%m%d_%H%M'),'run_started_at':run_started.isoformat(),'run_ended_at':run_started.isoformat(),'timezone':'Asia/Taipei','input_file':str(inp),'input_sha256':sha,'source_platform':'Threads','collector_tool':TOOL,'collector_version':VERSION,'retrieval_method':METHOD,'recent_search_verified':False,'network_requests_made':0,'search_keywords':search_keywords,'window_start':lo.isoformat(),'window_end':run_started.isoformat()}
    write_csv(out/'provenance.csv',[prov],list(prov))
    rawdir=root/'data/raw'/('run_'+run_started.strftime('%Y%m%d_%H%M')); rawdir.mkdir(parents=True,exist_ok=True)
    (rawdir/'collection_manifest.json').write_text(json.dumps(prov,ensure_ascii=False,indent=2),encoding='utf-8')
    report=root/'reports/validation_report.md'; report.parent.mkdir(parents=True,exist_ok=True)
    lines=['# Threads 全聯輿情資料蒐集 PoC v0.2 驗證報告','',f'- 測試型態：離線 replay；網路請求：0 次',f'- run_started_at：{run_started.isoformat()}（Asia/Taipei）',f'- 搜尋視窗：{lo.isoformat()} 至 {run_started.isoformat()}',f'- recent_search_verified：`false`',f'- 原始結果：{len(rows)} 筆；唯一 ID：{len({r["post_id"] for r in rows})} 筆',f'- 12 小時內且 direct_brand／brand_related：{len(eligible)} 筆；目標 20 筆：`{"達成" if len(eligible)>=20 else "未達成"}`',f'- 最新合格貼文：{eligible[0]["published_at_tw"] if eligible else "無"}；距 run start：{eligible[0]["age_hours"] if eligible else "N/A"} 小時','', '## 搜尋與來源限制','', '本次沒有新搜尋，因此無法報告 Tier 1／Tier 2 各自的網路取得筆數。既有 JSON 的 query 是「全聯」，本報告只對其做本機時間與相關性過濾。工具原始碼有 cursor 分頁與 replies limit，但 CLI 沒有 start_date／end_date 或已驗證 Recent 排序；結果也會依互動量排序，因此 `recent_search_verified=false`。','', '## Table A：最新貼文 Top 20','', table(eligible,fields), '', '## Table B：熱度貼文 Top 20','', table(heat,fields), '', '## 熱度公式','', '`heat_score = likes * 1 + replies * 3 + reposts * 4 + quotes * 2`。這是本次排序用啟發式分數，不是正式模型權重；互動值是擷取時快照。','', '## 來源與媒體網域','', f'- post_url_host：{count_hosts(rows,"post_url_host")}', f'- media_hosts：{count_media(rows)}', '- 媒體 URL 若出現 Instagram CDN，只代表檔案儲存網域；主平台仍依貼文 URL 判定為 Threads，不應誤分類為 Instagram。', '', '## 缺漏與研究限制','', '- 本次只留下既有搜尋結果中符合時間窗與品牌文字的資料，不能宣稱是 Threads 最近 12 小時完整貼文。', '- 不足 20 筆時沒有用舊貼文、其他品牌或背景詞補足。', '- `reply_count` 不是回覆全文；本次沒有執行 replies。', '- 互動數不是發文當下數值；沒有多次快照就不能計算真正互動成長率。', '- 逐小時統計只能描述觀測樣本，不能代表全平台聲量。', '', '## 結論','', f'本次離線資料在設定的 12 小時窗內只有 {len(eligible)} 筆合格全聯貼文，不能證實工具具備真正 Recent 排序或完整覆蓋。可支援資料管線與小時聚合示範，但尚不足以支撐事件級 6／12 小時預測研究。正式網路測試前仍需確認研究倫理、Meta／Threads 授權與資料保存規則。']
    report.write_text('\n'.join(lines),encoding='utf-8')
    return {'raw':len(rows),'eligible':len(eligible),'latest':eligible[0]['published_at_tw'] if eligible else None,'sha256':sha}
def table(rows,fields):
    cols=['post_id','published_at_tw','age_hours','like_count','reply_count','heat_score','post_url']; s=['| '+' | '.join(cols)+' |','|'+'|'.join(['---']*len(cols))+'|']
    for r in rows[:20]: s.append('| '+' | '.join(str(r.get(c,'')).replace('|',' ') for c in cols)+' |')
    return '\n'.join(s) if rows else '（0 筆）'
def count_hosts(rows,k):
    from collections import Counter
    return dict(Counter(r.get(k) for r in rows))
def count_media(rows):
    from collections import Counter
    c=Counter(); [c.update(r.get('media_hosts',[])) for r in rows]; return dict(c)
from datetime import timedelta
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--run-started-at',required=True); a=ap.parse_args(); print(json.dumps(build(Path(a.input),Path(__file__).parents[1],parse_dt(a.run_started_at)),ensure_ascii=False,indent=2))
