"""Explicit Excel -> annotation-state import. Never touches raw responses."""
import argparse
import hashlib
import json
from pathlib import Path

from core import MANUAL_FIELDS, TOPICS, SENTIMENTS, CRISES, utc_now
from xlsx_io import tabular

HEADERS = dict(zip(MANUAL_FIELDS, ('人工議題', '人工情緒', '人工情緒對象', '人工危機候選', '人工備註', '複核狀態')))


def import_rows(rows, records, state, reviewer, source):
    state = json.loads(json.dumps(state))
    state.setdefault('annotations', {})
    state.setdefault('history', [])
    known = {r['record_id']: r for r in records}
    seen = set()
    for row in rows:
        rid = row.get('record_id')
        if rid not in known or rid in seen:
            raise ValueError('missing/unknown/duplicate immutable record_id in review workbook')
        seen.add(rid)
        if row.get('原始貼文連結') != known[rid]['source_url']:
            raise ValueError('record_id and URL no longer match; import refused')
        values = {k: row.get(h) or None for k, h in HEADERS.items()}
        status = values['review_status'] or 'pending'
        if status not in ('pending', 'confirmed', 'corrected'):
            raise ValueError('invalid review_status')
        values['review_status'] = status
        for key, allowed in (('manual_topic', TOPICS), ('manual_sentiment', SENTIMENTS), ('manual_crisis_candidate', CRISES)):
            if values[key] is not None and values[key] not in allowed:
                raise ValueError(f'invalid {key}')
        if status in ('confirmed', 'corrected') and not all(values[k] is not None for k in ('manual_topic', 'manual_sentiment', 'manual_sentiment_target', 'manual_crisis_candidate')):
            raise ValueError('human confirmation requires topic, sentiment, target and crisis fields')
        old = state['annotations'].get(rid, {k: known[rid].get(k) for k in MANUAL_FIELDS})
        if values != old:
            state['history'].append(dict(record_id=rid, before=old, after=values,
                                         imported_at_utc=utc_now(), reviewer=reviewer, source=source))
            state['annotations'][rid] = values
    return state


def refuse_unimported_edits(xlsx, records):
    if not Path(xlsx).exists():
        return
    rows = tabular(xlsx, '全聯輿情分析')
    saved = {r['record_id']: r for r in records}
    for row in rows:
        r = saved.get(row.get('record_id'))
        if r is None:
            raise ValueError('existing workbook contains unmapped record_id; preserve it and import reviews first')
        if any((row.get(header) or None) != (r.get(k) or None) for k, header in HEADERS.items()):
            raise ValueError('Excel has unimported manual edits. Run reviews.py first; existing file is preserved.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--workbook', required=True, type=Path)
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--state', required=True, type=Path)
    ap.add_argument('--reviewer', required=True)
    a = ap.parse_args()
    state = json.loads(a.state.read_text()) if a.state.exists() else {}
    data = json.loads(a.data.read_text())
    source = {'file': str(a.workbook), 'sha256': hashlib.sha256(a.workbook.read_bytes()).hexdigest()}
    result = import_rows(tabular(a.workbook, '全聯輿情分析'), data['normalized_records'], state, a.reviewer, source)
    a.state.parent.mkdir(parents=True, exist_ok=True)
    a.state.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'history_entries': len(result['history']), 'annotated_records': len(result['annotations'])}))
