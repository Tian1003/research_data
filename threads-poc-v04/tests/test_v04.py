import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from build_v04 import build
class TestV04(unittest.TestCase):
    def test_canonical_import_preserves_null_fetch_time_and_string_id(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'p'; src=Path(d)/'x.json'; src.write_text(json.dumps({'query':'全聯','results':[{'id':12345678901234567890,'caption':'全聯好吃','taken_at':1793361600,'like_count':1,'reply_count':2,'repost_count':0,'quote_count':0,'url':'https://www.threads.com/t/x','media':[]}]}))
            data=build(src,root); r=data['normalized_records'][0]
            self.assertEqual(r['platform_content_id'],'12345678901234567890'); self.assertIsNone(r['actual_fetched_at_utc']); self.assertEqual(data['validation']['new_records'],0)
