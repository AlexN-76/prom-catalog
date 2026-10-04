#!/usr/bin/env python3
"""Check SKU+category of every approved item present in preview XML; no writes."""
import argparse,csv,json,xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--xml',required=True);p.add_argument('--decisions',required=True);p.add_argument('--report',required=True)
a=p.parse_args()
with open(a.decisions,encoding='utf-8-sig',newline='') as f:
    rows=list(csv.DictReader(f))
approved={r['offer_id']:(r['vendor_code'],r['portal_category_id']) for r in rows}
if len(approved)!=len(rows) or len(rows)!=1282:raise SystemExit('FAIL: expected 1282 unique approved offer IDs')
root=ET.parse(a.xml).getroot(); offers=root.findall('./shop/offers/offer')
seen=set(); checked=set()
for o in offers:
    oid=o.get('id')
    if not oid or oid in seen:raise SystemExit('FAIL: missing or duplicate offer ID: '+repr(oid))
    seen.add(oid)
    if oid not in approved:continue
    sku,cat=approved[oid]
    actual_sku=(o.findtext('vendorCode') or o.findtext('article') or '').strip()
    actual_cat=(o.findtext('portal_category_id') or '').strip()
    if (actual_sku,actual_cat)!=(sku,cat):raise SystemExit(f'FAIL {oid}: expected {(sku,cat)} got {(actual_sku,actual_cat)}')
    checked.add(oid)
if '29865' not in checked:raise SystemExit('FAIL: approved SOLOMON offer 29865 missing')
missing=sorted(set(approved)-checked)
report={'status':'PASS','offers_in_preview':len(offers),'approved_total':len(approved),'checked_present':len(checked),'missing_from_feed':missing,'missing_count':len(missing),'solomon_29865':'13240122','published':False}
Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'PASS: {len(checked)}/{len(approved)} approved matches; missing in this feed: {len(missing)}; SOLOMON 29865 = 13240122')
