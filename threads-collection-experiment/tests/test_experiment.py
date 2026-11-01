"""Offline fixtures reuse the user's real records. Tests never fetch Threads."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from data_pipeline import connect, load_json, batch_metrics, dataset_summary, records, ingest, validate_payload, parse_time, sha, refresh_assessments
from experiment import configuration, import_existing, planned_stage, run_live_stage, stopping_reason

CFG=configuration(ROOT/'config/experiment.json')
REVIEW=load_json(ROOT/'config/relevance_review.json')
BUNDLE=load_json(ROOT.parent/'threads-poc-v05/output/threads_raw_v05.json')
OLD=BUNDLE['raw_responses'][0]['response']
NEW=load_json(ROOT.parent/'threads-part2/run_20261031_210039/quanlian_core.json')
REFERENCE=parse_time('2026-10-31T13:00:44Z')


class ExistingDataTests(unittest.TestCase):
    def test_two_real_batches_overlap_and_unique_gain(self):
        old=batch_metrics(OLD,REVIEW,set(),set(),REFERENCE)
        ids={r['record_id'] for r in old['review_pending_rows']}
        brand={r['record_id'] for r in old['review_pending_rows'] if r['brand_candidate']}
        new=batch_metrics(NEW,REVIEW,ids,brand,REFERENCE)
        self.assertEqual((old['unique_ids'],new['unique_ids'],new['cross_batch_duplicate_count'],new['new_id_count']),(20,20,3,17))
        self.assertEqual(new['brand_candidate_count'],12)
        self.assertEqual(new['newly_retrieved_brand_count'],10)
        self.assertEqual(new['relevance_counts'],dict(direct=11,related=1,context_only=3,uncertain=5))

    def test_recency_uses_publication_and_fixed_captured_start(self):
        m=batch_metrics(NEW,REVIEW,set(),set(),REFERENCE)
        self.assertEqual(m['published_time_counts'],{'12h':3,'24h':8,'7d':9,'30d':13})
        self.assertEqual(m['brand_candidate_time_counts']['12h'],2)
        self.assertEqual(m['brand_candidate_time_counts']['24h'],5)

    def test_incidental_mentions_are_excluded(self):
        m=batch_metrics(NEW,REVIEW,set(),set(),REFERENCE)
        rows={r['record_id'].split(':')[-1]:r for r in m['review_pending_rows']}
        for pid in ('4019468788639407482','4019437810592506846','4020011414958323669'):
            self.assertFalse(rows[pid]['brand_candidate'])
            self.assertEqual(rows[pid]['brand_relevance'],'context_only')
        self.assertEqual(rows['4019457419885405557']['brand_relevance'],'related')

    def test_empty_bad_json_and_invalid_dates_do_not_create_valid_samples(self):
        self.assertTrue(validate_payload({'status':'ok','count':20,'results':[]}))
        m=batch_metrics({'status':'ok','count':0,'results':[]},REVIEW,set(),set(),REFERENCE)
        self.assertEqual(m['status'],'VALID_EMPTY');self.assertIsNone(m['duplicate_rate'])
        doc=copy.deepcopy(NEW);doc['results']=doc['results'][1:2];doc['count']=1
        for timestamp in (None,9999999999999):
            doc['results'][0]['taken_at']=timestamp
            m=batch_metrics(doc,REVIEW,set(),set(),REFERENCE)
            self.assertEqual(m['brand_candidate_count'],0)

    def test_import_twice_preserves_37_ids_and_40_observations(self):
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d)
            db=connect(tmp/'state.sqlite')
            # Existing source locations resolved against the real project; new DB/archive isolated.
            cfg=copy.deepcopy(CFG)
            for k in ('legacy_bundle','recorded_batch','recorded_start','recorded_finish'):
                cfg[k]=str((ROOT/cfg[k]).resolve())
            first=import_existing(cfg,tmp,db,REVIEW)
            second=import_existing(cfg,tmp,db,REVIEW)
            summary=dataset_summary(db)
            self.assertEqual(summary['unique_candidate_ids'],37)
            self.assertEqual(summary['observation_count'],40)
            self.assertEqual(summary['brand_candidate_count'],29)
            self.assertEqual(summary['human_confirmed_brand_count'],0)
            self.assertEqual(summary['source_window_observations'],20)
            self.assertEqual(summary['exact_observation_timestamps'],0)
            self.assertEqual(second['new_record_ids_inserted_this_execution'],0)
            self.assertEqual(second['newly_imported_sources_this_execution'],0)
            self.assertEqual(first['provided_capture_duration_seconds'],26)
            self.assertTrue(all(r['actual_fetched_at_utc'] is None for r in records(db)))
            refresh_assessments(db,REVIEW)
            self.assertEqual(refresh_assessments(db,REVIEW),0)
            self.assertEqual(dataset_summary(db)['brand_candidate_count'],29)
            self.assertEqual(dataset_summary(db)['observation_count'],40)
            db.close()

    def test_instrumented_receipts_keep_both_snapshots_and_manual_fields(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(Path(d)/'state.sqlite')
            raw=copy.deepcopy(NEW['results'][1])
            doc=dict(status='ok',count=1,query='全聯',results=[raw])
            rid='threads:post:'+raw['id']
            previous={rid:{'manual_note':'human note','review_status':'confirmed','manual_sentiment':'positive'}}
            observations=[]
            for i,likes in [(1,raw['like_count']),(2,raw['like_count']+10)]:
                observations.append(dict(id=raw['id'],text=raw['caption'],like_count=likes,
                    reply_count=raw['reply_count'],repost_count=raw['repost_count'],quote_count=raw['quote_count'],
                    request_id=i,request_started_at=f'2026-10-31T13:00:{i*10:02d}Z',response_received_at=f'2026-10-31T13:00:{i*10+1:02d}Z',raw_http_ref=f'fixture_http_{i}'))
            source=dict(source_id='TEST_HTTP',input_path='test fixture',sha256='fixture',origin='unit_test',
                start_utc='2026-10-31T13:00:00Z',finish_utc='2026-10-31T13:01:00Z',time_basis='instrumented_http',per_post_observations=observations)
            ingest(db,doc,source,REVIEW,previous)
            row=records(db)[0]
            self.assertEqual(row['actual_fetched_at_utc'],'2026-10-31T13:00:11Z')
            self.assertEqual(row['manual_note'],'human note')
            self.assertEqual(row['review_status'],'confirmed')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],2)
            self.assertEqual(dataset_summary(db)['records_with_two_exact_observation_times'],1)
            db.close()


class GatingTests(unittest.TestCase):
    def test_stage_b_cannot_start_from_offline_data(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(Path(d)/'state.sqlite')
            b=planned_stage(CFG,ROOT,'B',db)
            self.assertEqual(b['status'],'BLOCKED_AUTHORIZATION')
            self.assertTrue(any('Stage A' in s for s in b['blockers']))
            self.assertTrue(any('人工' in s for s in b['blockers']))
            c=planned_stage(CFG,ROOT,'C',db)
            self.assertEqual(c['status'],'DESIGN_ONLY');self.assertFalse(c['scheduler_installed'])
            db.close()

    def test_force_live_without_authorization_does_not_spawn_collector(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(Path(d)/'state.sqlite')
            p=planned_stage(CFG,ROOT,'A',db)
            with patch('experiment.subprocess.run') as child:
                result=run_live_stage(CFG,ROOT/'config/experiment.json',ROOT,db,REVIEW,p,'TEST_BLOCKED',Path(d))
            child.assert_not_called()
            self.assertEqual(result['http_request_count'],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM query_runs').fetchone()[0],4)
            db.close()

    def test_stalls_and_low_quality_stop_next_keyword(self):
        m=batch_metrics(NEW,REVIEW,set(),set(),REFERENCE)
        self.assertEqual(stopping_reason(m,CFG,2),'CONSECUTIVE_ZERO_NEW_BRAND_CANDIDATES')
        m['brand_candidate_count']=0
        self.assertEqual(stopping_reason(m,CFG,0),'LOW_BRAND_RELEVANCE_REVIEW_REQUIRED')


if __name__=='__main__':
    unittest.main()
