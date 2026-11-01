import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from build_poc import build, parse_dt

class TestPoc(unittest.TestCase):
    def test_window_and_heat(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'p'; src=Path(d)/'x.json'
            src.write_text(json.dumps({'query':'全聯','results':[{'id':'1','caption':'全聯 good','taken_at':datetime_ts('2026-10-30T20:00:00+08:00'),'like_count':1,'reply_count':2,'repost_count':0,'quote_count':0,'url':'https://www.threads.com/@a/post/x'},{'id':'2','caption':'全聯 old','taken_at':datetime_ts('2026-10-29T20:00:00+08:00'),'like_count':100,'reply_count':0,'repost_count':0,'quote_count':0,'url':'https://www.threads.com/@b/post/y'}]}))
            out=build(src,root,parse_dt('2026-10-31T00:00:00+08:00'))
            self.assertEqual(out['eligible'],1)
            self.assertEqual(json.loads((root/'data/processed/quanlian_12h_heat_ranked.csv').read_text(encoding='utf-8-sig').splitlines()[1].split(',')[9],),7)
def datetime_ts(s):
    from datetime import datetime
    return int(datetime.fromisoformat(s).timestamp())
