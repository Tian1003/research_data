#!/usr/bin/env python3
import argparse, csv, json, sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

POST_FIELDS = ['event_id','post_id','parent_post_id','root_post_id','author_id','text','published_at_utc','published_at_taipei','collected_at','source_url','search_keyword','is_reply','like_count','reply_count','repost_count','quote_count','data_source']

def iso(ts, tz=timezone.utc):
    if ts is None: return None
    try: return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(tz).isoformat()
    except (TypeError, ValueError, OverflowError): return None

def author_id(p):
    a=p.get('author') or p.get('user') or {}
    return str(a.get('id') or a.get('pk') or '') or None

def normalize_posts(doc, query, collected_at, run_id):
    out=[]; seen=set(); duplicates=0
    for p in doc.get('results', []):
        pid=str(p.get('id') or '')
        if not pid: continue
        if pid in seen: duplicates += 1; continue
        seen.add(pid)
        metrics=p.get('metrics') or {}
        out.append({'event_id':None,'post_id':pid,'parent_post_id':None,'root_post_id':pid,
          'author_id':author_id(p),'text':p.get('caption'),'published_at_utc':iso(p.get('taken_at')),
          'published_at_taipei':iso(p.get('taken_at'), ZoneInfo('Asia/Taipei')), 'collected_at':collected_at,
          'source_url':p.get('url'),'search_keyword':query,'is_reply':1 if p.get('is_reply') else 0,
          'like_count':p.get('like_count', metrics.get('likes')),'reply_count':p.get('reply_count', metrics.get('replies')),
          'repost_count':p.get('repost_count', metrics.get('reposts')),'quote_count':p.get('quote_count', metrics.get('quotes')),
          'data_source':'ckelepel-threads search'})
    return out, duplicates

def make_event(query, run_id, posts):
    # No event has been manually confirmed; event_id must remain NULL.
    return {'event_id':None,'event_name':None,'brand':None,'start_at_utc':None,'end_at_utc':None,'query':query,'notes':'事件標籤與時間窗尚未人工編碼'}

def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def write_db(path, posts, replies, events, runs):
    con=sqlite3.connect(path); con.executescript('''CREATE TABLE IF NOT EXISTS events(event_id TEXT,event_name TEXT,brand TEXT,start_at_utc TEXT,end_at_utc TEXT,query TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS posts(event_id TEXT,post_id TEXT PRIMARY KEY,parent_post_id TEXT,root_post_id TEXT,author_id TEXT,text TEXT,published_at_utc TEXT,published_at_taipei TEXT,collected_at TEXT,source_url TEXT,search_keyword TEXT,is_reply INTEGER,like_count INTEGER,reply_count INTEGER,repost_count INTEGER,quote_count INTEGER,data_source TEXT);
    CREATE TABLE IF NOT EXISTS replies(event_id TEXT,reply_id TEXT PRIMARY KEY,post_id TEXT,parent_post_id TEXT,root_post_id TEXT,author_id TEXT,text TEXT,published_at_utc TEXT,published_at_taipei TEXT,collected_at TEXT,source_url TEXT,search_keyword TEXT,is_reply INTEGER,like_count INTEGER,reply_count INTEGER,repost_count INTEGER,quote_count INTEGER,data_source TEXT);
    CREATE TABLE IF NOT EXISTS interaction_snapshots(post_id TEXT,observed_at TEXT,like_count INTEGER,reply_count INTEGER,repost_count INTEGER,quote_count INTEGER,run_id TEXT);
    CREATE TABLE IF NOT EXISTS collection_runs(run_id TEXT PRIMARY KEY,input_path TEXT,query TEXT,collected_at TEXT,post_count INTEGER,reply_count INTEGER,duplicate_count INTEGER,notes TEXT);''')
    con.executemany('INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)', [tuple(e.values()) for e in events])
    fields=POST_FIELDS; ph=','.join('?'*len(fields)); con.executemany(f'INSERT OR REPLACE INTO posts ({",".join(fields)}) VALUES ({ph})', [[p.get(k) for k in fields] for p in posts])
    con.executemany('INSERT INTO interaction_snapshots VALUES (?,?,?,?,?,?,?)', [(p['post_id'],p['collected_at'],p['like_count'],p['reply_count'],p['repost_count'],p['quote_count'],runs[0]['run_id']) for p in posts])
    con.executemany('INSERT OR REPLACE INTO collection_runs VALUES (?,?,?,?,?,?,?,?)', [tuple(r[k] for k in ['run_id','input_path','query','collected_at','post_count','reply_count','duplicate_count','notes']) for r in runs])
    con.commit(); con.close()

def run(inp, outdir, query, run_id):
    doc=json.loads(Path(inp).read_text(encoding='utf-8')); collected=datetime.now(timezone.utc).isoformat()
    posts, dups=normalize_posts(doc, query or doc.get('query'), collected, run_id); event=make_event(query or doc.get('query'),run_id,posts)
    outdir.mkdir(parents=True, exist_ok=True)
    write_csv(outdir/'posts.csv',posts,POST_FIELDS); write_csv(outdir/'replies.csv',[],POST_FIELDS)
    write_csv(outdir/'interaction_snapshots.csv',[{'post_id':p['post_id'],'observed_at':p['collected_at'],'like_count':p['like_count'],'reply_count':p['reply_count'],'repost_count':p['repost_count'],'quote_count':p['quote_count'],'run_id':run_id} for p in posts],['post_id','observed_at','like_count','reply_count','repost_count','quote_count','run_id'])
    write_csv(outdir/'events.csv',[event],list(event)); write_csv(outdir/'collection_runs.csv',[{'run_id':run_id,'input_path':str(inp),'query':query or doc.get('query'),'collected_at':collected,'post_count':len(posts),'reply_count':0,'duplicate_count':dups,'notes':'offline normalization; no reply payload'}],['run_id','input_path','query','collected_at','post_count','reply_count','duplicate_count','notes'])
    run_row={'run_id':run_id,'input_path':str(inp),'query':query or doc.get('query'),'collected_at':collected,'post_count':len(posts),'reply_count':0,'duplicate_count':dups,'notes':'offline normalization; no reply payload'}
    write_db(outdir/'threads_research.sqlite',posts,[],[event],[run_row])
    dates=[p['published_at_utc'] for p in posts if p['published_at_utc']]; authors={p['author_id'] for p in posts if p['author_id']}
    report={'input':str(inp),'status':doc.get('status'),'query':doc.get('query'),'declared_count':doc.get('count'),'normalized_posts':len(posts),'duplicate_ids':dups,'unique_authors':len(authors),'missing_by_field':{k:sum(p.get(k) is None for p in posts) for k in POST_FIELDS},'date_min_utc':min(dates) if dates else None,'date_max_utc':max(dates) if dates else None,'posts_with_positive_reply_count':sum((p.get('reply_count') or 0)>0 for p in posts),'reply_records_collected':0,'limitations':['search result is not a complete time series','reply_count is not reply text','no date filter was present','engagement metrics are collection-time cumulative values']}
    (outdir/'quality_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output-dir',required=True); ap.add_argument('--query'); ap.add_argument('--run-id',default='offline-run'); a=ap.parse_args(); print(json.dumps(run(Path(a.input),Path(a.output_dir),a.query,a.run_id),ensure_ascii=False,indent=2))
