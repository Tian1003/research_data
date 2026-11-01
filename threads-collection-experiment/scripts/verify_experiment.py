#!/usr/bin/env python3
"""Save reproducible offline verification results without re-running data collection."""
import io
import json
import re
import sqlite3
import subprocess
import unittest
from pathlib import Path

from data_pipeline import ROOT, load_json, sha, utc_now


def main():
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    config=load_json(ROOT/'config/experiment.json')
    node=subprocess.run([config['tool']['node_binary'],'--test',str(ROOT/'tests/transport.test.mjs')],capture_output=True,text=True)
    passed=re.search(r'^# pass (\d+)$',node.stdout,re.M)
    failed=re.search(r'^# fail (\d+)$',node.stdout,re.M)
    db=sqlite3.connect(ROOT/'data/experiment.sqlite')
    unchanged=[]
    for (raw,) in db.execute('SELECT metadata_json FROM sources'):
        s=json.loads(raw)
        if s['origin']=='legacy':
            unchanged.append(sha(Path(s['input_path']).read_bytes())==s['parent_container_sha256'])
        else:
            unchanged.append(sha(Path(s['input_path']).read_bytes())==s['sha256'])
            unchanged.extend(sha(Path(p).read_bytes())==h for p,h in s.get('timestamp_file_evidence',{}).items())
    count=db.execute('SELECT COALESCE(SUM(http_request_count),0) FROM query_runs').fetchone()[0]
    db.close()
    status=result.wasSuccessful() and node.returncode==0 and all(unchanged) and count==0
    data=dict(verified_at_utc=utc_now(),status='PASS' if status else 'FAIL',
              python_tests=result.testsRun,python_failures=len(result.failures),python_errors=len(result.errors),
              node_pass=int(passed[1]) if passed else None,node_fail=int(failed[1]) if failed else None,
              actual_threads_requests_in_current_experiment=count,input_integrity_checks_passed=all(unchanged),
              tests_use_mock_transport_only=True,live_collection_tested=False)
    target=ROOT/'data/verification_latest.json'
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    (ROOT/'data/python_test_results.txt').write_text(stream.getvalue())
    (ROOT/'data/node_test_results.txt').write_text(node.stdout+node.stderr)
    print(json.dumps(data,ensure_ascii=False,indent=2))
    return 0 if status else 1


if __name__=='__main__':
    raise SystemExit(main())
