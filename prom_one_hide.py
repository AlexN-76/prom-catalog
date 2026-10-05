#!/usr/bin/env python3
# coding: utf-8
"""Conservative, ONE-card Prom.ua hide. Offline by default; never runs in GitHub Actions.

Requires matched post-publication observer state and report, current feed, recent GET-only
Prom snapshot, manual-59 registry and historical ID/article file.

Execution requires explicit --execute, --confirm-internal-id and PROM_ENABLE_SINGLE_WRITE=YES.
No automatic batch mode. No token is stored or printed. No auto retries on POST.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import stat
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from prom_hide_review_plan import make_plan, read_csv, read_feed, norm, require

BASE_URL = "https://my.prom.ua/api/v1"
VALID_CURRENT_STATUS = "on_display"
HIDDEN_STATUS = "not_on_display"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("HTTP redirect blocked")


def api_json(opener, token, path, *, method="GET", payload=None):
    require(path.startswith("/products/") and path.count("/") >= 2,
            "unexpected API path")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "supplier-hide-single/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, headers=headers, data=data, method=method)
    # On errors, do not log response bodies: they might include sensitive details.
    try:
        with opener.open(req, timeout=25) as response:
            require(response.status == 200, "unexpected API HTTP response")
            require(response.geturl() == BASE_URL + path, "API URL changed")
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Prom API returned HTTP {exc.code}; no automatic retry") from None
    require(isinstance(result, dict), "unexpected API JSON response")
    return result


def product_from_response(resp):
    product = resp.get("product")
    require(isinstance(product, dict), "GET response missing 'product'")
    return product


def live_matches(candidate, product):
    rid = str(product.get("id", "")).strip()
    external = str(product.get("external_id") or "").strip()
    code = norm(product.get("sku"))
    return (
        rid == candidate["prom_internal_id"]
        and external == candidate["import_id"]
        and bool(code)
        and code == norm(candidate["sku"])
    )


def append_journal(directory, run, cid, event, **fields):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{now}_{run}_{cid}_{event}.json"
    path = directory / filename
    record = {"timestamp_utc": now, "run_id": str(run),
              "prom_internal_id": cid, "event": event, **fields}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return path


def load_and_plan(a):
    p = pathlib.Path(a.snapshot)
    age = (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 3600
    require(-0.1 <= age <= a.max_age_hours <= 6,
            "Prom snapshot is stale: refresh it via GET-only script")
    cols, snap = read_csv(a.snapshot)
    require({"prom_internal_id", "import_id", "sku", "status", "presence"}.issubset(cols),
            "snapshot lacks required columns")
    cols, manual = read_csv(a.protected, ";")
    require({"prom_internal_id", "prom_import_id", "sku", "protect"}.issubset(cols),
            "manual protection registry malformed")
    cols, baseline = read_csv(a.baseline)
    require({"offer_id", "article"}.issubset(cols), "baseline malformed")
    state = json.loads(pathlib.Path(a.state).read_text(encoding="utf-8-sig"))
    report = json.loads(pathlib.Path(a.report).read_text(encoding="utf-8-sig"))
    plan = make_plan(state, report, read_feed(a.feed), snap, manual, baseline)
    return plan, state, report


def execute_one(a, *, opener=None):
    plan, state, report = load_and_plan(a)
    verified = [c for c in plan if c["assessment"] == "review_only"]
    print(f"Observer run: {report['run_number']} ({report['run_id']})")
    print(f"Candidates: {len(plan)}, exact review-only: {len(verified)}")
    if not a.execute:
        print("OFFLINE PREVIEW. No API requests, no changes.")
        for c in verified[:10]:
            print("REVIEW:", c["prom_internal_id"], "import", c["import_id"],
                  "SKU", c["sku"], "streak", c["missing_streak"])
        return "preview"
    require(a.confirm_internal_id and a.confirm_internal_id.isdigit(),
            "--execute requires a numeric --confirm-internal-id")
    require(os.environ.get("PROM_ENABLE_SINGLE_WRITE") == "YES",
            "PROM_ENABLE_SINGLE_WRITE must equal YES for this command only")
    token = os.environ.get("PROM_API_TOKEN", "").strip()
    require(bool(token), "PROM_API_TOKEN not set (never share token)")
    matches = [c for c in verified if c["prom_internal_id"] == a.confirm_internal_id]
    require(len(matches) == 1, "this internal ID is NOT uniquely approved for review")
    c = matches[0]
    require(c["status"] == VALID_CURRENT_STATUS,
            "snapshot status is not on_display; refusing to modify")
    require(c["missing_streak"] >= 3, "not enough fresh absences")
    # Prevent a retry by accident if a previous POST outcome is uncertain.
    journal = pathlib.Path(a.journal)
    if journal.exists():
        attempted = list(journal.glob(f"*_{report['run_id']}_{c['prom_internal_id']}_POST_ATTEMPT.json"))
        require(not attempted, "an attempt exists for this run/product: manual inspection required")
    opener = opener or urllib.request.build_opener(NoRedirect())
    product = product_from_response(api_json(opener, token, f"/products/{c['prom_internal_id']}"))
    require(live_matches(c, product), "live Prom identity changed: refusing POST")
    require(product.get("status") == VALID_CURRENT_STATUS,
            "live Prom status changed: refusing POST")
    print("Live GET identity/status: OK")
    print("Will change exactly ONE internal ID:", c["prom_internal_id"])
    print("Status:", VALID_CURRENT_STATUS, "->", HIDDEN_STATUS)
    append_journal(journal, report["run_id"], c["prom_internal_id"], "POST_ATTEMPT",
                   external_id=c["import_id"], sku=c["sku"],
                   previous_status=VALID_CURRENT_STATUS,
                   desired_status=HIDDEN_STATUS)
    # Prom Products edit accepts JSON ARRAY of individual product edits.
    # No other fields are transmitted; never reuse a full product object.
    payload = [{"id": int(c["prom_internal_id"]), "status": HIDDEN_STATUS}]
    try:
        response = api_json(opener, token, "/products/edit", method="POST", payload=payload)
        if response.get("errors") or response.get("error"):
            raise ValueError("Prom reported edit errors; inspect manually")
        after = product_from_response(api_json(
            opener, token, f"/products/{c['prom_internal_id']}"))
        require(live_matches(c, after), "GET after POST returned unexpected product")
        require(after.get("status") == HIDDEN_STATUS,
                "post-write GET did not confirm hidden status")
    except Exception:
        append_journal(journal, report["run_id"], c["prom_internal_id"],
                       "NEEDS_MANUAL_VERIFICATION")
        raise RuntimeError("POST was attempted. Result uncertain: CHECK CARD IN PROM; NO RETRY") from None
    append_journal(journal, report["run_id"], c["prom_internal_id"],
                   "VERIFIED_HIDDEN", external_id=c["import_id"], sku=c["sku"])
    print("SUCCESS: one card verified as not_on_display. Journal:", journal)
    return "verified"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "report", "feed", "snapshot", "protected", "baseline"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--journal", default="prom_hide_journal")
    p.add_argument("--max-age-hours", type=int, default=6)
    p.add_argument("--execute", action="store_true", help="Explicit ONE-card write; never scheduled")
    p.add_argument("--confirm-internal-id", default="")
    args = p.parse_args()
    try:
        execute_one(args)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        sys.exit("STOP: " + str(exc))


if __name__ == "__main__":
    main()
