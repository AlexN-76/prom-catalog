#!/usr/bin/env python3
"""Apply reviewed Prom portal-category IDs to a NEW XML file (post-hybrid, no publication).
Requires exact offer ID + vendorCode match. Changes portal_category_id only.
"""
import argparse,csv,gzip,json,os,tempfile
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

def csv_dicts(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def load_allow_list(reference, extra):
    allowed={}
    for path,idfield in [(reference,'portal_category_id'),(extra,'portal_category_id')]:
        for n,r in enumerate(csv_dicts(path),2):
            category=(r.get(idfield) or '').strip()
            if not category:
                raise ValueError(f'{path}:{n} empty category id')
            name=(r.get('prom_category_name') or r.get('category_name') or '').strip()
            allowed.setdefault(category,name)
    return allowed

def run(args):
    input_path=Path(args.input)
    output_path=Path(args.output)
    if input_path.resolve()==output_path.resolve():
        raise ValueError('Input and output XML must be different files.')
    valid_ids=load_allow_list(args.reference,args.extra_categories)
    reviewed={}
    for lineno,r in enumerate(csv_dicts(args.decisions),2):
        oid=(r.get('offer_id') or '').strip()
        sku=(r.get('vendor_code') or '').strip()
        cat=(r.get('portal_category_id') or '').strip()
        if not (oid and sku and cat): raise ValueError(f'Incomplete rule, CSV row {lineno}')
        if oid in reviewed: raise ValueError(f'Duplicate review offer ID: {oid}')
        if cat not in valid_ids: raise ValueError(f'Unknown category {cat} in row {lineno}')
        reviewed[oid]=(sku,cat)
    inp_open=gzip.open if input_path.suffix.lower()=='.gz' else open
    with inp_open(input_path,'rb') as fd:
        root=ET.parse(fd).getroot()
    offers=root.findall('./shop/offers/offer')
    if not offers:
        raise RuntimeError('No offers in input XML')
    changed=0;unchanged=0;seen=set();checked=set()
    for o in offers:
        oid=(o.get('id') or '').strip()
        if not oid or oid in seen:raise ValueError('Missing or duplicate offer id: '+repr(oid))
        seen.add(oid)
        rule=reviewed.get(oid)
        if rule is None: continue
        sku,approved=rule
        current_sku=((o.findtext('vendorCode') or o.findtext('article') or '').strip())
        if current_sku!=sku:
            raise ValueError(f'Identity guard: offer {oid}: reviewed SKU {sku!r}, feed SKU {current_sku!r}; STOP, no output published.')
        tag=o.find('portal_category_id')
        old=(tag.text or '').strip() if tag is not None else ''
        if tag is None:tag=ET.SubElement(o,'portal_category_id')
        tag.text=approved
        checked.add(oid)
        if old!=approved:changed+=1
        else: unchanged+=1
    missing=sorted(reviewed.keys()-checked)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp_path=tempfile.mkstemp(prefix='.categories_reviewed_',suffix='.xml',dir=output_path.parent)
    try:
        with os.fdopen(fd,'wb') as tmp:
            ET.ElementTree(root).write(tmp,encoding='utf-8',xml_declaration=True)
        ET.parse(tmp_path)
        os.replace(tmp_path,output_path)
    finally:
        if os.path.exists(tmp_path):os.unlink(tmp_path)
    result={
      'source_offers':len(offers), 'reviewed_rules':len(reviewed),
      'rules_applied':len(checked),'category_values_changed':changed,
      'category_values_unchanged':unchanged,'reviewed_offers_missing_from_this_feed':missing,
      'data_modified':'offer portal_category_id only',
      'published':False,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**result,'reviewed_offers_missing_from_this_feed_count':len(missing)},ensure_ascii=False,indent=2) if args.verbose else
       f'PASS: {len(checked)}/{len(reviewed)} reviewed; categories changed {changed}; skipped absent {len(missing)}; input preserved')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--decisions',default='prom_reviewed_category_decisions_1282.csv')
    parser.add_argument('--reference',default='prom_reference_categories.csv')
    parser.add_argument('--extra-categories',default='prom_reviewed_extra_categories.csv')
    parser.add_argument('--report',default='prom_reviewed_category_report.json')
    parser.add_argument('--verbose',action='store_true')
    run(parser.parse_args())
