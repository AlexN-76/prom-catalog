#!/usr/bin/env python3
"""Check that reviewed XML differs from its input ONLY in offer portal_category_id.

Usage:
    python3 validate_prom_category_diff.py \
        --input preview_hybrid.xml --output preview_reviewed.xml \
        --report prom_hybrid_category_report.json

The --report argument is accepted for compatibility with the GitHub workflow.
It is not written to, because it belongs to the existing hybrid-classifier job.
"""
import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


def load_xml(path):
    p = Path(path)
    opener = gzip.open if p.suffix.lower() == '.gz' else open
    with opener(p, 'rb') as stream:
        return ET.parse(stream).getroot()


def meaningful(text):
    return '' if not text or not text.strip() else text


def compare(a, b, path='root', in_offer=False):
    if a.tag != b.tag:
        raise ValueError(f'{path}: element changed: {a.tag!r} to {b.tag!r}')
    if a.attrib != b.attrib:
        raise ValueError(f'{path}: XML attributes changed')
    if meaningful(a.text) != meaningful(b.text):
        raise ValueError(f'{path}: text changed')
    if meaningful(a.tail) != meaningful(b.tail):
        raise ValueError(f'{path}: tail text changed')
    here_is_offer = a.tag == 'offer'
    left = [c for c in a if not (here_is_offer and c.tag == 'portal_category_id')]
    right = [c for c in b if not (here_is_offer and c.tag == 'portal_category_id')]
    if len(left) != len(right):
        raise ValueError(f'{path}: child elements added or removed')
    for i, (l, r) in enumerate(zip(left, right), start=1):
        compare(l, r, f'{path}/{l.tag}[{i}]')


def offers(root):
    result = root.findall('./shop/offers/offer')
    ids = [o.get('id', '') for o in result]
    if not result or any(not x for x in ids):
        raise ValueError('Missing offers or offer ID')
    dup = [x for x, n in Counter(ids).items() if n != 1]
    if dup:
        raise ValueError(f'Duplicate offer IDs: {dup[:10]}')
    return result


def run(args):
    original = load_xml(args.input)
    reviewed = load_xml(args.output)
    first, second = offers(original), offers(reviewed)
    compare(original, reviewed)
    changes = 0
    for before, after in zip(first, second):
        if before.get('id') != after.get('id'):
            raise ValueError('Offer order or ID changed')
        orig_tags = before.findall('portal_category_id')
        new_tags = after.findall('portal_category_id')
        if len(orig_tags) > 1 or len(new_tags) > 1:
            raise ValueError(f'Duplicate portal_category_id in offer {before.get("id")}')
        old = (orig_tags[0].text or '').strip() if orig_tags else ''
        new = (new_tags[0].text or '').strip() if new_tags else ''
        if old != new:
            changes += 1
    print(f'PASS: {len(first)} offers; {changes} category values changed; all other fields and offer IDs unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--report', default='', help='Compatibility argument; existing report is kept intact')
    run(parser.parse_args())
