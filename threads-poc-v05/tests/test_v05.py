"""Offline tests. Artificial request/observation metadata stays in temporary fixtures only."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from core import parse_time, excel_serial, normalize, snapshot, merge_records, apply_reviews, classify, utc_now
from official_probe import plan, execute, response_envelope
from reviews import import_rows, HEADERS, refuse_unimported_edits
from xlsx_io import tabular, read_sheet, validate_workbook, NS, M

LEGACY=json.loads((ROOT.parent/'quanlian.json').read_text())


def test_run(tool='ckelepel-threads',keyword='全聯',observed=None):
    return dict(run_id='TEST_ONLY_'+keyword,collector=tool,collector_version=None,
                collection_method='keyword_search',data_origin='legacy' if observed is None else 'test_fixture',
                response_received_at=observed,search_keywords=[keyword],raw_response_id='TEST_ONLY',result_path='results')


def record():
    return normalize(LEGACY['results'][0],test_run(),0,'2026-10-31T12:19:14+00:00')


class TimeTests(unittest.TestCase):
    def test_two_required_utc_to_taipei_cases(self):
        for source,expected in [('2026-10-30T12:23:50Z','2026-10-30T20:23:50+08:00'),('2025-10-02T10:00:29Z','2025-10-02T18:00:29+08:00')]:
            from core import TW
            self.assertEqual(parse_time(source).astimezone(TW).isoformat(),expected)
            wall=datetime(1899,12,30)+timedelta(days=excel_serial(source))
            self.assertAlmostEqual((wall-datetime.fromisoformat(expected).replace(tzinfo=None)).total_seconds(),0,places=3)

    def test_seconds_milliseconds_and_invalid_values(self):
        sec=LEGACY['results'][0]['taken_at']
        self.assertEqual(parse_time(sec),parse_time(sec*1000))
        for x in (None,True,'broken','2026-01-01T00:00:00',float('nan'),float('inf')):
            self.assertIsNone(parse_time(x))


class CanonicalTests(unittest.TestCase):
    def test_real_twenty_rows_preserve_ids_and_null_fetch_time(self):
        rows=[normalize(p,test_run(),i,utc_now()) for i,p in enumerate(LEGACY['results'])]
        self.assertEqual(len(rows),20)
        self.assertEqual(len({r['record_id'] for r in rows}),20)
        self.assertTrue(all(isinstance(r['platform_content_id'],str) for r in rows))
        self.assertTrue(all(r['actual_fetched_at_utc'] is None for r in rows))
        self.assertEqual(rows[0]['record_id'],'threads:post:'+LEGACY['results'][0]['id'])

    def test_large_numeric_id_has_no_float_conversion(self):
        p=copy.deepcopy(LEGACY['results'][0]); p['id']=1234567890123456789012345
        self.assertEqual(normalize(p,test_run(),0,utc_now())['platform_content_id'],str(p['id']))

    def test_cross_keyword_tool_dedup_and_snapshot_history(self):
        a=record()
        p=LEGACY['results'][0]
        b=normalize(dict(id=p['id'],text=p['caption'],permalink=p['url'],timestamp=a['published_at_utc'],like_count=8,reply_count=2,repost_count=1,quote_count=0),test_run('threads-content-research-agent','pxmart','2026-10-31T12:20:00+00:00'),0,utc_now())
        c=copy.deepcopy(b); c['actual_fetched_at_utc']='2026-10-31T13:20:00+00:00'; c['like_count']=12
        merged=merge_records([a,b,c]); snaps=list(map(snapshot,[a,b,c]))
        self.assertEqual(len(merged),1); self.assertEqual(merged[0]['search_keywords'],['全聯','pxmart'])
        self.assertEqual(len({s['snapshot_id'] for s in snaps}),3)
        self.assertEqual([s['like_count'] for s in snaps],[p['like_count'],8,12])
        self.assertIsNone(snaps[0]['observed_at_utc'])

    def test_missing_values_are_not_zero_or_fake_score(self):
        p=copy.deepcopy(LEGACY['results'][0]); p.pop('metrics'); p.pop('like_count')
        r=normalize(p,test_run(),0,utc_now())
        self.assertIsNone(r['like_count']); self.assertIsNone(r['heat_score'])

    def test_media_host_does_not_define_source_platform(self):
        r=normalize(LEGACY['results'][1],test_run(),1,utc_now())
        self.assertEqual(r['source_platform'],'threads')
        self.assertTrue(any('instagram' in h for h in r['media_hosts']))
        p=copy.deepcopy(LEGACY['results'][1]); p['url']='https://example.org/a'
        self.assertEqual(normalize(p,test_run(),1,utc_now())['source_platform'],'unknown')

    def test_replies_discard_collector_inferred_time_and_parent(self):
        p=dict(id='9000000000000001',text='reply fixture',is_reply=True,url='https://www.threads.com/t/TEST',created_at=1793448000,parent_id=LEGACY['results'][0]['id'],post_id=LEGACY['results'][0]['id'])
        run=test_run(); run['collection_method']='replies'
        r=normalize(p,run,0,utc_now())
        self.assertIsNone(r['published_at_utc']); self.assertIsNone(r['parent_content_id'])
        self.assertEqual(r['content_type'],'reply')


class ClassificationReviewTests(unittest.TestCase):
    def test_negative_other_brand_is_not_assigned_to_pxmart(self):
        text='全聯的鮮凍白蝦仁很好吃，比好市多好很多，好市多讓我過敏。'
        r=classify(text)
        self.assertEqual(r['sentiment'],'positive'); self.assertEqual(r['sentiment_target'],'全聯商品')
        self.assertEqual(r['review_priority'],'high'); self.assertEqual(r['crisis_candidate'],'no')

    def test_irony_remains_uncertain_and_pending(self):
        r=classify('在全聯被我抓到最後一盒，拜託大家不要去買。')
        self.assertEqual(r['sentiment'],'uncertain'); self.assertEqual(r['crisis_candidate'],'uncertain')
        self.assertEqual(r['review_status'],'pending'); self.assertTrue(r['review_required'])
        self.assertNotEqual(r['topic_category'],'品牌爭議')

    def test_human_import_preserves_system_values_and_history(self):
        r=record(); original=copy.deepcopy(r)
        row={h:r.get(k) for k,h in HEADERS.items()}
        row.update(record_id=r['record_id'],原始貼文連結=r['source_url'])
        row.update({'人工議題':'門市服務','人工情緒':'neutral','人工情緒對象':'全聯','人工危機候選':'no','人工備註':'TEST_ONLY human review','複核狀態':'confirmed'})
        state=import_rows([row],[r],{},'test reviewer',{'fixture':True})
        apply_reviews([r],state)
        self.assertEqual(r['topic_category'],original['topic_category'])
        self.assertEqual(r['manual_sentiment'],'neutral'); self.assertEqual(r['review_status'],'confirmed')
        self.assertEqual(len(state['history']),1)
        self.assertEqual(state['history'][0]['before']['manual_sentiment'],None)
        self.assertEqual(len(import_rows([row],[r],state,'test',{})['history']),1)

    def test_wrong_id_url_and_premature_confirmation_refused(self):
        r=record()
        row={h:r.get(k) for k,h in HEADERS.items()}; row.update(record_id=r['record_id'],原始貼文連結=r['source_url'])
        row['複核狀態']='confirmed'
        with self.assertRaises(ValueError): import_rows([row],[r],{},'test',{})
        row['複核狀態']='pending'; row['原始貼文連結']='https://wrong.example/'
        with self.assertRaises(ValueError): import_rows([row],[r],{},'test',{})


class AcquisitionTests(unittest.TestCase):
    def test_no_authorization_no_network(self):
        cfg=json.loads((ROOT/'config/run.json').read_text())
        p=plan(cfg,token_present=True)
        mock=Mock()
        with self.assertRaises(PermissionError): execute(p,'TEST_ONLY',mock)
        mock.assert_not_called(); self.assertEqual(p['status'],'BLOCKED')

    def test_empty_and_failed_are_not_reported_as_acquired(self):
        p={'mode':'search','endpoint':'keyword_search','params':{'q':'全聯'}}
        for code,body,status,count in [(200,b'{"data":[]}','EMPTY',0),(403,b'{"error":{"code":10}}','FAILED',None),(429,b'{"error":{"code":429}}','FAILED',None)]:
            e=response_envelope(p,body,code,'2026-10-31T00:00:00+00:00','2026-10-31T00:00:01+00:00')
            self.assertEqual(e['run']['status'],status); self.assertEqual(e['run']['result_count'],count)
            self.assertEqual(e['run']['response_received_at'],'2026-10-31T00:00:01+00:00')

    def test_successful_response_has_request_received_time(self):
        # Existing real post reused as a mocked API response, never added to research output.
        p={'mode':'search','endpoint':'keyword_search','params':{'q':'全聯'}}
        raw=json.dumps({'data':[{'id':LEGACY['results'][0]['id']}]}).encode()
        e=response_envelope(p,raw,200,'2026-10-31T00:00:00Z','2026-10-31T00:00:01Z')
        self.assertEqual(e['run']['status'],'SUCCESS'); self.assertEqual(e['run']['result_count'],1)
        self.assertIsNotNone(e['run']['actual_fetched_at_utc'])


class DeliverableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'output/threads_raw_v05.json'
        cls.data=json.loads(cls.path.read_text())

    def test_raw_response_is_intact_and_only_three_files(self):
        self.assertEqual(self.data['raw_responses'][0]['response'],LEGACY)
        original=(ROOT.parent/'quanlian.json').read_bytes()
        self.assertEqual(self.data['raw_responses'][0]['raw_utf8'].encode(),original)
        self.assertEqual(hashlib.sha256(original).hexdigest(),self.data['validation']['original_file_sha256'])
        self.assertEqual({p.name for p in (ROOT/'output').iterdir()}, {'threads_raw_v05.json','threads_analysis_v05.xlsx','data_feasibility_v05.md'})

    def test_xlsx_dates_sort_links_filters_dropdowns_round_trip(self):
        result=validate_workbook(ROOT/'output/threads_analysis_v05.xlsx',self.data)
        self.assertEqual(result['checked_rows'],20)
        rows=tabular(ROOT/'output/threads_analysis_v05.xlsx','全聯輿情分析')
        by_id={r['record_id']:r for r in rows}
        for r in self.data['normalized_records']:
            if r['published_at_utc'] in ('2026-10-30T12:23:50+00:00','2025-10-02T10:00:29+00:00'):
                d=datetime(1899,12,30)+timedelta(days=by_id[r['record_id']]['發布時間（台灣）'])
                self.assertEqual(d.strftime('%Y/%m/%d %H:%M'),datetime.fromisoformat(r['published_at_tw']).strftime('%Y/%m/%d %H:%M'))

    def test_manual_workbook_changes_are_guarded(self):
        source=ROOT/'output/threads_analysis_v05.xlsx'
        refuse_unimported_edits(source,self.data['normalized_records'])
        with tempfile.TemporaryDirectory() as d:
            edited=Path(d)/'edited.xlsx'
            with zipfile.ZipFile(source) as z:
                parts={n:z.read(n) for n in z.namelist()}
            xml=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
            c=xml.find('.//m:c[@r="U2"]',NS)
            if c is None:
                row=xml.find('.//m:row[@r="2"]',NS)
                c=ET.SubElement(row,f'{{{M}}}c',{'r':'U2'})
            c.clear(); c.set('r','U2'); c.set('t','inlineStr')
            ET.SubElement(ET.SubElement(c,f'{{{M}}}is'),f'{{{M}}}t').text='TEST_ONLY manual edit'
            parts['xl/worksheets/sheet1.xml']=ET.tostring(xml)
            with zipfile.ZipFile(edited,'w') as z:
                for n,b in parts.items(): z.writestr(n,b)
            with self.assertRaises(ValueError): refuse_unimported_edits(edited,self.data['normalized_records'])

    def test_statistics_agree_between_json_xlsx_report(self):
        st=self.data['validation']['statistics']
        sm={r['項目']:r['結果'] for r in tabular(ROOT/'output/threads_analysis_v05.xlsx','資料驗證摘要')}
        for label,key in [('總唯一全聯貼文數','total_unique_posts'),('本次新增唯一全聯貼文數','new_unique_posts'),('新搜尋請求次數','search_request_count'),('實際取得回覆全文紀錄數','observed_reply_records')]:
            self.assertEqual(sm[label],st[key])
        self.assertEqual(st['new_unique_posts'],0); self.assertEqual(st['search_request_count'],0)
        self.assertEqual(st['displayed_reply_count_sum'],2074)
        self.assertEqual(len(self.data['interaction_snapshots']),20)
        self.assertTrue(all(s['observed_at_utc'] is None for s in self.data['interaction_snapshots']))
        text=(ROOT/'output/data_feasibility_v05.md').read_text()
        self.assertIn('0 篇全聯貼文、0 則回覆',text)
        self.assertTrue(all(r['review_status']=='pending' for r in self.data['normalized_records']))


if __name__=='__main__':
    unittest.main()
