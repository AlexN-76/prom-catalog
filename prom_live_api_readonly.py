#!/usr/bin/env python3
# coding: utf-8
"""Prom.ua Products READ-ONLY diagnostic, no mutation HTTP endpoints, no token in files.

Modes:
    --check  : GET 3 entries, print only non-sensitive fields.
    --full   : GET pages of Products with strict pagination and write a minimal snapshot.
Fail-closed: if complete catalog cannot be verified, no CSV is written.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://my.prom.ua/api/v1/products/list'
FIELDS = ['prom_internal_id', 'import_id', 'sku', 'name', 'availability_code', 'status', 'presence']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP redirect blocked: refusing to forward API credentials')


def fetch(token, limit, last_id=None):
    qs = {'limit': str(limit)}
    if last_id is not None:
        qs['last_id'] = str(last_id)
    url = API + '?' + urllib.parse.urlencode(qs)
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
        'User-Agent': 'prom-safe-audit-readonly/0.2',
    }, method='GET')
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError('Unexpected API status')
                if response.geturl().split('?',1)[0] != API:
                    raise ValueError('Unexpected API host/path')
                data = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise ValueError(f'API HTTP {exc.code}. Проверить права Products и срок действия токена.') from None
    if not isinstance(data, dict) or not isinstance(data.get('products'), list):
        raise ValueError('Unexpected JSON: products list missing')
    if not all(isinstance(item, dict) for item in data['products']):
        raise ValueError('Unexpected API product structure')
    return data['products']


def trim(item):
    internal = str(item.get('id') or '').strip()
    external = str(item.get('external_id') or '').strip()
    if not internal.isdigit():
        raise ValueError('Invalid product internal ID returned by API')
    presence = str(item.get('presence') or '').strip()
    status = str(item.get('status') or '').strip()
    return {
        'prom_internal_id': internal,
        'import_id': external,
        'sku': str(item.get('sku') or '').strip(),
        'name': str(item.get('name') or '').strip(),
        'availability_code': presence,
        'status': status,
        'presence': presence,
    }


def run(check, output, min_expected):
    token = os.environ.get('PROM_API_TOKEN', '').strip()
    if not token:
        raise ValueError('PROM_API_TOKEN not configured. Token should stay on your computer.')
    if check:
        rows = fetch(token, 3)
        print('GET Products OK. Received:', len(rows))
        for item in rows:
            row = trim(item)
            print({key: row[key] for key in ('prom_internal_id','import_id','sku','status','presence')})
        print('Changes made: 0. Token not saved.')
        return

    page_size = 100
    products, seen = [], set()
    last_id = None
    pages = 0
    # Hard cap prevents infinite loops if pagination is broken or unsupported.
    while pages < 300:
        page = fetch(token, page_size, last_id)
        pages += 1
        if not page:
            if not products:
                raise ValueError('API gave no products; incomplete catalog')
            break
        page_rows = [trim(p) for p in page]
        page_ids = [int(r['prom_internal_id']) for r in page_rows]
        if len(set(page_ids)) != len(page_ids):
            raise ValueError('Duplicate IDs within API page: stop; pagination unreliable')
        if seen.intersection(str(i) for i in page_ids):
            raise ValueError('Repeated product IDs across pages: stop; pagination unreliable')
        if last_id is not None and max(page_ids) >= last_id:
            raise ValueError('API cursor did not move to older IDs: stop; pagination unreliable')
        seen.update(str(i) for i in page_ids)
        products.extend(page_rows)
        print(f'API page {pages}: {len(page_rows)} items; accumulated {len(products)}', flush=True)
        if len(page) < page_size:
            break
        next_cursor = min(page_ids)
        if last_id is not None and next_cursor >= last_id:
            raise ValueError('Pagination failed to advance')
        last_id = next_cursor
    else:
        raise ValueError('Maximum API pages reached, catalog completeness unknown')
    if len(products) < min_expected:
        raise ValueError(f'Only {len(products)} products, expected >= {min_expected}. NOT SAVED.')
    # Local snapshot contains no API token and no personal customer data.
    destination = Path(output)
    if destination.exists():
        raise ValueError('Output already exists; refuse to overwrite a previous snapshot')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8-sig', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader(); wr.writerows(products)
    print('API snapshot saved:', destination.resolve())
    print('Products:',len(products),'pages:',pages,'writes to Prom.ua: 0')


def main():
    p = argparse.ArgumentParser(description='Read-only Prom.ua Products audit')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='Check existing token and sample 3 products')
    mode.add_argument('--full',action='store_true',help='Read ALL products into local CSV, never modify Prom')
    p.add_argument('--output',default='prom_live_snapshot.csv')
    p.add_argument('--min-expected',type=int,default=10000,
        help='Abort without output when unexpectedly fewer products returned')
    args = p.parse_args()
    if args.min_expected < 10000:
        raise ValueError('Cannot weaken minimum count in safety audit')
    run(args.check,args.output,args.min_expected)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print('STOP:',exc,file=sys.stderr)
        sys.exit(2)
