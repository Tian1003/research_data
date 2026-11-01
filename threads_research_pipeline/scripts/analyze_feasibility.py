import json, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).parents[2]; INPUT=ROOT/'quanlian.json'; REPORTS=ROOT/'threads_research_pipeline/reports'
NOW=datetime(2026,10,31,0,0,tzinfo=ZoneInfo('Asia/Taipei')).astimezone(timezone.utc)
TAIPEI=ZoneInfo('Asia/Taipei')

def dt(p): return datetime.fromtimestamp(p['taken_at'],timezone.utc)
def fmt(d): return d.astimezone(TAIPEI).strftime('%Y-%m-%d %H:%M')
def quant(v):
    s=sorted(v); return {'min':min(s),'p25':s[len(s)//4],'median':statistics.median(s),'p75':s[(3*len(s))//4],'max':max(s)}

doc=json.loads(INPUT.read_text()); rows=doc['results']; likes=[p['like_count'] for p in rows]; replies=[p['reply_count'] for p in rows]
missing={k:sum(k not in p or p[k] is None for p in rows)/len(rows) for k in sorted(set().union(*(p.keys() for p in rows)))}
recent={f'{days}d':sum(dt(p)>=NOW-timedelta(days=days) for p in rows) for days in [1,7,30]}
age_bins=Counter(); hot_bins=Counter(); cross=Counter()
rank={p['id']:i+1 for i,p in enumerate(sorted(rows,key=lambda p:(p['like_count']+p['reply_count']),reverse=True))}
for p in rows:
    age=(NOW-dt(p)).total_seconds()/86400
    age_bin='0-24h' if age<=1 else '1-7d' if age<=7 else '8-30d' if age<=30 else '30d+'
    hot='high(top 1/3)' if rank[p['id']]<=7 else 'medium(mid 1/3)' if rank[p['id']]<=14 else 'low(bottom 1/3)'
    age_bins[age_bin]+=1; hot_bins[hot]+=1; cross[(age_bin,hot)]+=1
recent_top10=sum(dt(p)>=NOW-timedelta(days=7) for p in sorted(rows,key=lambda p:(p['like_count']+p['reply_count']),reverse=True)[:10])
hour=Counter(dt(p).astimezone(TAIPEI).strftime('%Y-%m-%d %H:00') for p in rows)
summary={'posts':len(rows),'unique_post_ids':len({str(p['id']) for p in rows}),'duplicate_id_rate':1-len({str(p['id']) for p in rows})/len(rows),'date_min_taipei':fmt(min(rows,key=lambda p:p['taken_at']).__class__ and dt(min(rows,key=lambda p:p['taken_at']))),'date_max_taipei':fmt(dt(max(rows,key=lambda p:p['taken_at']))),'recent_counts':recent,'like_distribution':quant(likes),'reply_distribution':quant(replies),'missing_field_rate':missing,'positive_reply_count':sum(p['reply_count']>0 for p in rows),'keyword_in_caption':sum('全聯' in (p.get('caption') or '') for p in rows),'age_bins':dict(age_bins),'heat_bins':dict(hot_bins),'age_heat_cross':{f'{a}|{h}':n for (a,h),n in sorted(cross.items())},'recent_7d_in_top10_by_engagement':recent_top10,'recent_7d_if_all_results':recent['7d'],'hourly_observed_post_counts':dict(sorted(hour.items())),'caveat':'These are observed search results, not platform-wide volume.'}
REPORTS.mkdir(parents=True,exist_ok=True); (REPORTS/'analysis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

sample=sorted(rows,key=lambda p:dt(p),reverse=True)[:10]
with (REPORTS/'manual_review_sample.md').open('w',encoding='utf-8') as f:
    f.write('# 人工檢查樣本（最多 10 筆）\n\n')
    f.write('以下僅提供人工判讀，不自動標註危機、負面情緒或事件。\n\n')
    for i,p in enumerate(sample,1): f.write(f"{i}. **{fmt(dt(p))}｜讚 {p['like_count']}｜回覆數 {p['reply_count']}**\n   - 文字：{(p.get('caption') or '').replace(chr(10),' ')[:180]}\n   - 來源：{p.get('url')}\n   - 待判斷：品牌相關性／一般分享／抱怨或爭議／是否需查證事件背景\n\n")
