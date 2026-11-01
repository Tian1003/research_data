#!/usr/bin/env python3
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

UTC=timezone.utc; TW=ZoneInfo('Asia/Taipei'); TOOL='ckelepel-threads'; VERSION='0.1.1'
def host(u): return urlparse(u).hostname if u else None
def media_hosts(v):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            for k,y in x.items():
                if k=='url' and isinstance(y,str) and host(y) and host(y) not in out: out.append(host(y))
                else: walk(y)
        elif isinstance(x,list):
            for y in x: walk(y)
    walk(v); return out
def dtime(ts):
    try: return datetime.fromtimestamp(float(ts),UTC)
    except (TypeError,ValueError,OverflowError): return None
def classify(t):
    t=t or ''
    topic='商品體驗'
    reasons=[]
    if any(k in t for k in ['抓到','拜託大家不要','不演了','氣爆','生氣']): topic='品牌爭議'; reasons.append('可能為反諷或負面事件，需人工確認')
    elif any(k in t for k in ['貴','特價','折','元','點數']): topic='價格與促銷'
    elif any(k in t for k in ['wifi','門市','分店','店員']): topic='門市服務'
    elif any(k in t for k in ['蕁麻疹','硬又沒有蝦味','生','過期']): topic='商品品質'; reasons.append('疑似品質或食品安全語境，需人工確認')
    sentiment='uncertain'
    if any(k in t for k in ['生氣','氣爆','不演了','蕁麻疹','貴']): sentiment='negative'
    elif any(k in t for k in ['好吃','好喝','方便','可愛','推薦','幸運','給力']): sentiment='positive'
    if sentiment=='uncertain': reasons.append('規則無法明確判定情緒')
    if any(k in t for k in ['？','?','！','!']) and sentiment!='uncertain': reasons.append('語氣或反諷脈絡可能影響分類')
    return topic,sentiment,sorted(set(reasons))
def build(inp,root):
    raw=json.loads(Path(inp).read_text(encoding='utf-8')); processed=datetime.now(UTC).isoformat(); sha=hashlib.sha256(Path(inp).read_bytes()).hexdigest(); run_id='legacy_offline_'+datetime.now(TW).strftime('%Y%m%d_%H%M%S')
    records=[]; snapshots=[]
    for i,p in enumerate(raw.get('results',[])):
        pid=str(p.get('id')) if p.get('id') is not None else None; pub=dtime(p.get('taken_at')); topic,sent,reasons=classify(p.get('caption'))
        vals=[p.get('like_count'),p.get('reply_count'),p.get('repost_count'),p.get('quote_count')]; complete=all(isinstance(v,(int,float)) for v in vals)
        r={'record_id':f'threads:post:{pid}','source_platform':'threads','collector_tool':TOOL,'collector_version':VERSION,'collection_method':'keyword_search','run_id':run_id,'search_keywords':[raw.get('query')] if raw.get('query') else [],'brand':'全聯','brand_relevance':'direct','event_id':None,'content_type':'post','platform_content_id':pid,'parent_content_id':None,'root_content_id':pid,'source_url':p.get('url'),'text':p.get('caption'),'published_at_utc':pub.isoformat() if pub else None,'published_at_tw':pub.astimezone(TW).isoformat() if pub else None,'actual_fetched_at_utc':None,'processed_at_utc':processed,'like_count':p.get('like_count'),'reply_count':p.get('reply_count'),'repost_count':p.get('repost_count'),'quote_count':p.get('quote_count'),'topic_category':topic,'sentiment':sent,'review_required':True,'review_reasons':reasons or ['尚未完成正式人工標註'],'review_status':'pending','raw_source_ref':f'quanlian.json#/results/{i}','post_url_host':host(p.get('url')),'media_hosts':media_hosts(p.get('media')),'heat_score':(vals[0]+3*vals[1]+4*vals[2]+2*vals[3]) if complete else None,'heat_score_complete':complete,'manual_topic_category':None,'manual_sentiment':None,'manual_note':None}
        records.append(r)
    coll={'run_id':run_id,'request_started_at':None,'response_received_at':None,'query':raw.get('query'),'collector':TOOL,'collector_version':VERSION,'status':'LEGACY_IMPORT','result_count':len(raw.get('results',[])),'actual_fetched_at_utc':None,'note':'既有檔案匯入；本次未發出網路請求'}
    top={'schema_version':'0.4','collection_runs':[coll],'raw_responses':[{'raw_source_ref':'quanlian.json','source_path':str(Path(inp).resolve()),'sha256':sha,'response':raw}],'normalized_records':records,'interaction_snapshots':snapshots,'validation':{'authorization_status':'BLOCKED_AUTHORIZATION','network_requests_made':0,'legacy_records':len(records),'new_records':0,'deduplicated_records':len({r['record_id'] for r in records}),'reply_records_collected':0,'notes':['舊資料沒有可靠實際擷取時間','互動數不能回填為歷史觀測快照','本次沒有新搜尋或 replies 測試']}}
    out=root/'output'; out.mkdir(parents=True,exist_ok=True); (out/'threads_raw_v04.json').write_text(json.dumps(top,ensure_ascii=False,indent=2),encoding='utf-8')
    latest=max((r for r in records if r['published_at_utc']),key=lambda r:r['published_at_utc'],default=None)
    report=f'''# Threads 品牌輿情研究 PoC v0.4 可行性報告

## 總結

- 授權狀態：`BLOCKED_AUTHORIZATION`
- 本次新搜尋：0 次。既有 20 筆資料僅作 legacy import，沒有冒充新資料。
- 去重後既有貼文：{len({r['record_id'] for r in records})} 筆。
- 最近 12／24／7／30 天：依既有離線基準無法視為新取得樣本；可參考舊資料的發布時間，但不代表完整母體。
- 最新既有貼文：{latest['published_at_tw'] if latest else 'NULL'}。

## 六項問題狀態

| 項目 | 狀態 | 證據 |
|---|---|---|
| P1 Excel 台灣時間 | PASS | Excel 使用真正日期值、`YYYY/MM/DD HH:mm`、固定標題列與篩選 |
| P2 情緒／議題人工複核 | PARTIAL | 20 筆全部 `review_status=pending`，保留複核原因，未標記 confirmed |
| P3 真實擷取時間 | FAIL（舊資料） | 舊資料 `actual_fetched_at_utc=NULL`；新搜尋未執行 |
| P4 最新搜尋／偏差 | NOT_TESTED | 原始碼確認有 cursor 邏輯，但沒有 Recent／日期區間 CLI；未做新網路測試 |
| P5 真實留言 | BLOCKED_AUTHORIZATION | replies 未執行，實際回覆紀錄 0，發布時間比例 N/A |
| P6 模型資料量 | PARTIAL | 有 20 筆可整理貼文，沒有足夠連續事件、回覆或歷史快照 |

## 工具能力

`ckelepel-threads` v0.1.1 的 `search` 有 cursor continuation 與 `--limit`，但 CLI 沒有 `start_date`、`end_date` 或已驗證 Recent 模式；程式最後依關鍵字符合與互動量排序，存在熱門內容偏差。`replies` 有 `--limit`，但本次未執行。

第二套工具 `threads-content-research-agent` 是 Go、Apache-2.0 的唯讀研究 CLI，README 說明支援公開搜尋、可見 replies、JSONL／SQLite 與 bounded research，但也明確說不是官方 API、不是完整搜尋引擎，搜尋可能為空且覆蓋不完整；需要 Go 1.26+。本次未建置、未搜尋、無法比較實測聯集或重複率。

## 模型可行性

### Model A：情緒／議題分類

目前只能作為人工標註資料整理起點。20 筆不足以評估類別平衡；規則分類不是 ground truth，且全部標為 pending。建議先取得 300–500 筆經人工確認的多日期貼文，再檢查商品、品質、價格、服務與爭議類別是否足夠。

### Model B：未來 6／12 小時升溫預測

目前不具備足夠條件。缺少多個獨立事件、事件前後完整觀測、可靠逐小時覆蓋、歷史互動 snapshots 與可避免資料洩漏的時間點資料。不能把既有 20 筆搜尋結果當成完整事件時間序列。

## 下一步

取得適用的研究／平台資料授權後，先以小量 Tier 1 關鍵字執行 Level 1，保存每次原始 response、request／response 時間與錯誤；再進行兩篇 replies、最多 10–20 則的驗證。只有在覆蓋率、日期分布、人工標註與事件數量足夠後，才評估 300–500 筆分類資料或約 10 個可比較事件。
'''
    (out/'data_feasibility_v04.md').write_text(report,encoding='utf-8')
    return top
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); a=ap.parse_args(); print(json.dumps(build(Path(a.input),Path(__file__).parents[1]),ensure_ascii=False,indent=2)[:500])
