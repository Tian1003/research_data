import csv, json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from build_v03 import build
class TestV03(unittest.TestCase):
    def test_output_has_single_analysis_table_and_null_fetch_time(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'p'; src=Path(d)/'in.json'; src.write_text(json.dumps({'query':'全聯','results':[{'id':'9','caption':'全聯很好吃','taken_at':1793361600,'like_count':2,'reply_count':1,'repost_count':0,'quote_count':0,'url':'https://www.threads.com/@x/post/y','media':[]}]}))
            build(src,root,__import__('datetime').datetime.fromisoformat('2026-10-31T00:00:00+08:00'))
            with (root/'data/processed/threads_analysis.csv').open(encoding='utf-8-sig') as f: row=next(csv.DictReader(f))
            self.assertEqual(row['post_id'] if 'post_id' in row else 'missing','missing')
            prov=(root/'data/processed/data_provenance.csv').read_text(encoding='utf-8-sig'); self.assertIn(',,',prov)
