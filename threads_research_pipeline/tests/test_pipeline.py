import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from pipeline import normalize_posts, run

class PipelineTests(unittest.TestCase):
    def test_id_is_string_and_duplicates_are_removed(self):
        rows, dups=normalize_posts({'results':[{'id':123,'caption':'x','taken_at':0},{'id':'123','caption':'y'}]},'q','now','r')
        self.assertEqual(len(rows),1); self.assertEqual(dups,1); self.assertEqual(rows[0]['post_id'],'123')
    def test_missing_fields_are_null_and_no_fake_replies(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'in.json'; src.write_text(json.dumps({'status':'ok','query':'q','count':1,'results':[{'id':'1','caption':'x','taken_at':1700000000,'reply_count':4}]}))
            out=Path(d)/'out'; report=run(src,out,None,'r')
            self.assertEqual(report['reply_records_collected'],0); self.assertEqual(report['normalized_posts'],1)
            self.assertTrue((out/'threads_research.sqlite').exists())

if __name__=='__main__': unittest.main()
