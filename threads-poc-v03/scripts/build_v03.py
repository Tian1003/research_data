#!/usr/bin/env python3
import argparse, csv, hashlib, json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TW=ZoneInfo('Asia/Taipei'); UTC=timezone.utc
TOOL='ckelepel-threads'; VERSION='0.1.1'; FORMULA='likes*1 + replies*3 + reposts*4 + quotes*2'

def dt(ts):
    try: return datetime.fromtimestamp(float(ts),UTC)
    except (TypeError,ValueError,OverflowError): return None
def host(url): return urlparse(url).hostname if url else None
def media_hosts(x):
    out=[]
    def walk(v):
        if isinstance(v,dict):
            for k,z in v.items():
                if k=='url' and isinstance(z,str) and host(z) and host(z) not in out: out.append(host(z))
                else: walk(z)
        elif isinstance(v,list):
            for z in v: walk(z)
    walk(x); return out
def topic(text):
    t=text or ''
    if any(k in t for k in ['爭議','爆料','投訴','氣爆','抓到','不演了']): return '品牌爭議'
    if any(k in t for k in ['價格','特價','折','元','便宜','貴','點數']): return '價格與促銷'
    if any(k in t for k in ['門市','店員','服務','分店','wifi']): return '門市服務'
    if any(k in t for k in ['過期','品質','壞','臭','蕁麻疹','生','不新鮮']): return '商品品質'
    if any(k in t for k in ['好吃','好喝','推薦','買到','新品','商品','雞蛋豆腐','優格','藍莓','蝦仁','便當','餅乾','蛋餅','雞湯']): return '商品體驗'
    return '待判定'
def sentiment(text):
    t=text or ''
    neg=['生氣','氣爆','不演了','貴','藏在','僅剩','蕁麻疹','疑惑','到底','糟','壞','過期','投訴']
    pos=['好吃','好喝','推薦','幸運','方便','漂亮','可愛','給力','可以','滿意','喜歡']
    n=sum(k in t for k in neg); p=sum(k in t for k in pos)
    if n and not p: return '負面'
    if p and not n: return '正面'
    if n and p: return '待判定'
    return '待判定'
def norm(p, run_start, search_keyword, processed_at):
    published=dt(p.get('taken_at')); age=((run_start-published).total_seconds()/3600) if published else None
    vals=[p.get('like_count'),p.get('reply_count'),p.get('repost_count'),p.get('quote_count')]
    complete=all(isinstance(v,(int,float)) for v in vals); heat=(vals[0]+3*vals[1]+4*vals[2]+2*vals[3]) if complete else None
    return {'post_id':str(p['id']) if p.get('id') is not None else None,'published_at_tw':published.astimezone(TW).isoformat() if published else None,'age_hours':round(age,4) if age is not None else None,'text':p.get('caption'),'brand':'全聯','topic_category':topic(p.get('caption')),'sentiment':sentiment(p.get('caption')),'like_count':p.get('like_count'),'reply_count':p.get('reply_count'),'repost_count':p.get('repost_count'),'quote_count':p.get('quote_count'),'heat_score':heat,'heat_complete':complete,'heat_rank':None,'post_url':p.get('url'),'source_platform':'Threads','collector_tool':TOOL,'collector_version':VERSION,'retrieval_method':'offline replay of existing search JSON','post_url_host':host(p.get('url')),'media_hosts':media_hosts(p.get('media')),'search_keyword':search_keyword,'published_at_utc':published.isoformat() if published else None,'original_taken_at':p.get('taken_at'),'actual_fetched_at':None,'processed_at':processed_at,'raw_file_path':str(Path('quanlian.json').resolve()),'run_id':'offline_'+run_start.strftime('%Y%m%d_%H%M'),'is_reply':p.get('is_reply'),'parent_post_id':None,'root_post_id':str(p['id']) if p.get('id') is not None else None,'manual_topic_category':None,'manual_sentiment':None}
def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
def build(inp,root,run_start):
    doc=json.loads(Path(inp).read_text(encoding='utf-8')); processed=datetime.now(UTC).isoformat(); rows=[norm(p,run_start,doc.get('query'),processed) for p in doc.get('results',[])]
    ranked=sorted(rows,key=lambda r:(r['heat_score'] is not None,r['heat_score'] or -1,r['published_at_tw'] or ''),reverse=True)
    for i,r in enumerate(ranked,1): r['heat_rank']=i
    out=root/'data/processed'; out.mkdir(parents=True,exist_ok=True)
    fields=['published_at_tw','text','brand','topic_category','sentiment','like_count','reply_count','repost_count','quote_count','heat_score','heat_rank','post_url']
    write_csv(out/'threads_analysis.csv',rows,fields)
    with (out/'posts_normalized.jsonl').open('w',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
    review_fields=['post_id','published_at_tw','text','post_url','rule_topic_category','rule_sentiment','manual_topic_category','manual_sentiment','reviewer_note']
    write_csv(out/'manual_review.csv',[{'post_id':r['post_id'],'published_at_tw':r['published_at_tw'],'text':r['text'],'post_url':r['post_url'],'rule_topic_category':r['topic_category'],'rule_sentiment':r['sentiment'],'manual_topic_category':None,'manual_sentiment':None,'reviewer_note':None} for r in rows],review_fields)
    prov_fields=['post_id','source_platform','collector_tool','collector_version','retrieval_method','post_url_host','media_hosts','search_keyword','published_at_utc','actual_fetched_at','processed_at','raw_file_path','run_id']
    write_csv(out/'data_provenance.csv',[{k:r[k] for k in prov_fields} for r in rows],prov_fields)
    (root/'data/raw').mkdir(parents=True,exist_ok=True); (root/'data/raw/README.md').write_text(f'原始檔案保持在：{Path(inp).resolve()}\nSHA256：{hashlib.sha256(Path(inp).read_bytes()).hexdigest()}\n本次未複製或覆寫原始 JSON。\n',encoding='utf-8')
    lo=run_start-timedelta(hours=12); eligible=[r for r in rows if r['published_at_utc'] and lo<=datetime.fromisoformat(r['published_at_utc'])<=run_start and '全聯' in (r['text'] or '')]
    latest=sorted(eligible,key=lambda r:r['published_at_tw'] or '',reverse=True)
    report=root/'reports/validation_report_v03.md'; report.parent.mkdir(parents=True,exist_ok=True)
    def table(rs):
        s=['| 發布時間 | 內容 | 議題 | 情緒 | 讚 | 回覆 | 熱度 | 排名 | 來源 |','|---|---|---|---|---:|---:|---:|---:|---|']
        for r in rs[:5]: s.append('| '+' | '.join(str(r.get(k) or '').replace('|',' ') for k in ['published_at_tw','text','topic_category','sentiment','like_count','reply_count','heat_score','heat_rank','post_url'])+' |')
        return '\n'.join(s) if rs else '（無資料）'
    lines=['# Threads 輿情資料分析整理與近期資料取得驗證（PoC v0.3）','',f'- 分析資料：{len(rows)} 筆既有貼文，唯一 ID：{len({r["post_id"] for r in rows})} 筆', '- 本次新網路搜尋：否，0 次',f'- 離線觀測基準：{run_start.isoformat()}（Asia/Taipei）',f'- 12 小時視窗：{lo.isoformat()} 至 {run_start.isoformat()}',f'- 視窗內全聯相關貼文：{len(eligible)} 筆，目標 20 篇：{"達成" if len(eligible)>=20 else "未達成"}',f'- 最新貼文：{latest[0]["published_at_tw"] if latest else "無"}', '', '## 已完成且驗證成功','', '- 已建立單一主要分析表 `threads_analysis.csv`，包含時間、內容、議題、情緒、互動與熱度排名。', '- 已建立 `manual_review.csv`，規則分類可由研究者人工修正。', '- 已區分 Threads 貼文平台與 Instagram CDN 媒體網域。', '- `actual_fetched_at` 保持 NULL，沒有把離線整理時間冒充實際取得時間。', '', '## 熱度前 5 篇','', table(ranked), '', '## 分類說明','', '議題與情緒為簡單規則的暫定標籤，不能直接視為人工編碼、情緒模型結果或危機判定。負面情緒不等於公關危機。', '', '## 工具近期搜尋能力','', '本機 CLI Help 只有 `search`、`--limit`、`--no-strict`、`--no-expand`、輸出格式、Cookie、Proxy、dataset 與 db；沒有 start_date、end_date 或 Recent 參數。原始碼有 cursor 分頁，但工具最後依關鍵字符合度及互動量排序。故目前不能證實真正的最新排序或完整歷史覆蓋。', '', '## 尚未執行與限制','', '- 尚未執行新的網路搜尋，原因是研究使用授權尚未確認。', '- 尚未取得 replies 實際回覆全文與真實回覆發布時間。', '- 互動值是擷取時累積快照，不是發文當下數值。', '- 單一搜尋結果不能代表 Threads 全平台聲量。', '- 可做貼文內容人工檢查、時間分布與觀測互動排序；尚不能做完整事件逐小時聲量或可靠 6／12 小時預測。']
    report.write_text('\n'.join(lines),encoding='utf-8')
    return {'posts':len(rows),'eligible_12h':len(eligible),'latest':latest[0]['published_at_tw'] if latest else None}
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--run-started-at',required=True); a=ap.parse_args(); print(json.dumps(build(Path(a.input),Path(__file__).parents[1],datetime.fromisoformat(a.run_started_at).astimezone(TW)),ensure_ascii=False,indent=2))
