"""Small OOXML reader/verification helper. Dates decoded independently of the writer."""
import hashlib
import json
import posixpath
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'m': M, 'r': R}


def sheet_parts(z):
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    return {s.attrib['name']: posixpath.normpath('xl/' + rels[s.attrib[f'{{{R}}}id']])
            if not rels[s.attrib[f'{{{R}}}id']].startswith('/') else rels[s.attrib[f'{{{R}}}id']].lstrip('/')
            for s in wb.findall('m:sheets/m:sheet', NS)}


def read_sheet(path, name):
    with zipfile.ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        sheet = ET.fromstring(z.read(sheet_parts(z)[name]))
        rows = []
        for row in sheet.findall('m:sheetData/m:row', NS):
            result = {}
            for c in row.findall('m:c', NS):
                typ = c.attrib.get('t')
                v = c.find('m:v', NS)
                value = v.text if v is not None else None
                if typ == 's' and value is not None:
                    value = strings[int(value)]
                elif typ == 'inlineStr':
                    value = ''.join(c.find('m:is', NS).itertext())
                elif typ not in ('str', 'd', 'e') and value is not None:
                    value = float(value)
                    if value.is_integer():
                        value = int(value)
                result[''.join(x for x in c.attrib['r'] if x.isalpha())] = value
            rows.append((int(row.attrib['r']), result))
        return sheet, rows


def tabular(path, name):
    _, rows = read_sheet(path, name)
    headers = rows[0][1]
    return [{header: row.get(col) for col, header in headers.items() if header}
            for _, row in rows[1:] if row]


def add_native_links_and_hide_id(path):
    """Complete native links, hidden immutable ID and filters omitted by writer export."""
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
        part = sheet_parts(z)['全聯輿情分析']
    _, rows = read_sheet(path, '全聯輿情分析')
    sheet = ET.fromstring(parts[part])
    relpath = posixpath.dirname(part) + '/_rels/' + posixpath.basename(part) + '.rels'
    rels = ET.fromstring(parts[relpath]) if relpath in parts else ET.Element(f'{{{P}}}Relationships')
    for existing in list(rels):
        if existing.attrib.get('Id','').startswith('rIdSource'):
            rels.remove(existing)
    for existing in sheet.findall('m:hyperlinks', NS):
        sheet.remove(existing)
    links = ET.Element(f'{{{M}}}hyperlinks')
    for number, row in rows[1:]:
        url = row.get('O')
        if not isinstance(url, str) or not url.startswith('https://'):
            continue
        rid = f'rIdSource{number}'
        ET.SubElement(links, f'{{{M}}}hyperlink', {'ref': f'O{number}', f'{{{R}}}id': rid})
        ET.SubElement(rels, f'{{{P}}}Relationship', {'Id': rid, 'Type': R + '/hyperlink', 'Target': url, 'TargetMode': 'External'})
    # hyperlinks belongs after dataValidations, before pageMargins in the OOXML order.
    before = ('printOptions', 'pageMargins', 'pageSetup', 'headerFooter', 'tableParts', 'extLst')
    at = next((i for i, c in enumerate(sheet) if c.tag.split('}')[-1] in before), len(sheet))
    sheet.insert(at, links)
    cols = sheet.find('m:cols', NS)
    if cols is None:
        cols = ET.Element(f'{{{M}}}cols')
        sheet.insert(list(sheet).index(sheet.find('m:sheetData', NS)), cols)
    for col in list(cols):
        first, last = int(col.attrib['min']), int(col.attrib['max'])
        if first <= 23 <= last:
            attrs = dict(col.attrib)
            cols.remove(col)
            if first < 23:
                ET.SubElement(cols, f'{{{M}}}col', {**attrs, 'max': '22'})
            if last > 23:
                ET.SubElement(cols, f'{{{M}}}col', {**attrs, 'min': '24'})
    ET.SubElement(cols, f'{{{M}}}col', {'min': '23', 'max': '23', 'hidden': '1', 'width': '20', 'customWidth': '1'})
    cols[:] = sorted(cols, key=lambda c: int(c.attrib['min']))
    parts[part] = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
    parts[relpath] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    for name in list(parts):
        if name.startswith('xl/tables/') and name.endswith('.xml'):
            table = ET.fromstring(parts[name])
            if table.find('m:autoFilter', NS) is None:
                table.insert(0, ET.Element(f'{{{M}}}autoFilter', {'ref': table.attrib['ref']}))
            parts[name] = ET.tostring(table, encoding='utf-8', xml_declaration=True)
    temp = Path(path).with_suffix('.tmp.xlsx')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, content in parts.items():
            z.writestr(n, content)
    temp.replace(path)


def validate_workbook(path, data):
    sheet, rows = read_sheet(path, '全聯輿情分析')
    actual = tabular(path, '全聯輿情分析')
    expected = {r['record_id']: r for r in data['normalized_records'] if r['content_type'] == 'post' and r['brand_relevance'] in ('direct', 'related')}
    assert len(actual) == len(expected)
    serials = []
    checks = []
    for row in actual:
        r = expected[row['record_id']]
        serial = row['發布時間（台灣）']
        assert isinstance(serial, (int, float)), 'Excel date must be numeric'
        wall = datetime(1899, 12, 30) + timedelta(days=serial)
        parsed = datetime.fromisoformat(r['published_at_tw']).replace(tzinfo=None)
        assert abs((wall - parsed).total_seconds()) < 0.001
        assert row['貼文內容'] == r['text']
        assert row['按讚數'] == r['like_count']
        assert row['回覆數'] == r['reply_count']
        assert row['熱度分數'] == (r['heat_score'] if r['heat_score'] is not None else '不可計算')
        serials.append(serial)
        checks.append({'record_id': r['record_id'], 'excel_serial': serial, 'taipei_wall_clock': wall.isoformat(), 'expected': r['published_at_tw']})
    assert serials == sorted(serials, reverse=True)
    assert sheet.find('m:sheetViews/m:sheetView/m:pane', NS) is not None
    assert sheet.find('m:dataValidations', NS) is not None
    assert len(sheet.findall('m:hyperlinks/m:hyperlink', NS)) == len(actual)
    assert any(c.attrib.get('hidden') == '1' and c.attrib['min'] == '23' for c in sheet.findall('m:cols/m:col', NS))
    with zipfile.ZipFile(path) as z:
        assert len(sheet_parts(z)) == 2
        assert any('autoFilter' in z.read(n).decode() for n in z.namelist() if n.startswith('xl/tables/'))
        styles = ET.fromstring(z.read('xl/styles.xml'))
        assert any('yyyy/mm/dd hh:mm' == x.attrib.get('formatCode', '').lower() for x in styles.findall('m:numFmts/m:numFmt', NS))
        assert z.testzip() is None
    return {'status': 'PASS', 'checked_rows': len(actual), 'numeric_taipei_dates': True, 'sorted_latest_first': True, 'native_hyperlinks': len(actual), 'samples': checks[:2], 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx', type=Path)
    ap.add_argument('data', type=Path)
    ap.add_argument('--finalize', action='store_true')
    a = ap.parse_args()
    if a.finalize:
        add_native_links_and_hide_id(a.xlsx)
    print(json.dumps(validate_workbook(a.xlsx, json.loads(a.data.read_text())), ensure_ascii=False, indent=2))
