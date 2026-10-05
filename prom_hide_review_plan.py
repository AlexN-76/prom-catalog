#!/usr/bin/env python3
# coding: utf-8
"""Prom.ua: OFFLINE review of candidate IDs. Never calls Prom.ua or changes product statuses.

Inputs: GitHub observer state and corresponding report, published XML, recent
Prom GET-only snapshot, the protected-59 list, and historical Prom ID/SKU CSV.
Output: local CSV with human review decisions, NEVER executable hide instructions.
"""
import argparse
import csv
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SUPPLIERS = {"1": "SANDI", "2": "VALESO", "3": "RS4U",
             "4": "B2B-SKLAD", "5": "OL Infrastructure"}
CSV_COLUMNS = ["prom_internal_id", "import_id", "sku", "status", "presence",
               "supplier", "missing_streak", "assessment", "reason"]


def require(ok, why):
    if not ok:
        raise ValueError("STOP: " + why)


def norm(x):
    s = str(x or "").strip()
    return (s.lstrip("0") or "0") if re.fullmatch(r"\d+", s) else s


def read_csv(path, delimiter=","):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        columns = set(reader.fieldnames or [])
        return columns, list(reader)


def read_feed(path):
    ids = set()
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag == "offer":
            oid = (element.get("id") or "").strip()
            require(oid and oid not in ids, "duplicate or empty XML ID")
            ids.add(oid)
            element.clear()
    require(len(ids) >= 10000, "published feed unexpectedly small")
    return ids


def make_plan(state, report, feed_ids, snapshot_rows, manual_rows, baseline_rows):
    require(state.get("schema") == "supplier_absence_state_v1", "wrong state schema")
    history = state.get("last_known_category_by_id")
    streak = state.get("missing_streak")
    require(isinstance(history, dict) and len(history) == state.get("historical_ids_count"),
            "history inconsistent")
    require(isinstance(streak, dict), "missing counters malformed")
    for oid, n in streak.items():
        require(oid in history and type(n) is int and n > 0, "invalid missing counter")
    require(report.get("mode") == "READ_ONLY_DRY_RUN" and not report.get("skipped"),
            "observer report not a completed dry-run")
    require(report.get("no_prom_api_calls") is True, "unexpected observer mode")
    require(str(report.get("run_id")) == str(state.get("last_processed_workflow_run_id"))
            and report.get("run_number") == state.get("last_processed_workflow_run_number"),
            "observer report does not correspond to saved state")
    require(str(report.get("run_id")) in set(map(str, state.get("processed_generation_ids", []))),
            "run not recorded as processed")
    suppliers = report.get("suppliers")
    require(isinstance(suppliers, dict) and set(suppliers) == set(SUPPLIERS.values()),
            "incomplete supplier report")
    candidates = report.get("candidates_for_manual_review")
    require(isinstance(candidates, list) and len(candidates) == report.get("candidate_review_only"),
            "candidate list missing/inconsistent")
    require(len(snapshot_rows) >= 10000, "snapshot unexpectedly small")
    require(len(manual_rows) == 59, "manual protection registry must have exactly 59 entries")
    by_internal = {}
    by_import = defaultdict(list)
    for r in snapshot_rows:
        rid = (r.get("prom_internal_id") or "").strip()
        require(rid.isdigit() and rid not in by_internal, "duplicate/invalid Prom internal ID")
        by_internal[rid] = r
        ext = (r.get("import_id") or "").strip()
        if ext:
            by_import[ext].append(r)
    manual_internal, manual_import, manual_sku = set(), set(), set()
    for r in manual_rows:
        require((r.get("protect") or "").strip().upper() == "YES", "unprotected registry row")
        rid = (r.get("prom_internal_id") or "").strip()
        require(rid.isdigit() and rid not in manual_internal, "invalid protected internal ID")
        manual_internal.add(rid)
        ext = (r.get("prom_import_id") or "").strip()
        if ext:
            manual_import.add(ext)
        if norm(r.get("sku")):
            manual_sku.add(norm(r.get("sku")))
    # Stop rather than silently overlooking protected cards omitted by a partial snapshot.
    require(manual_internal.issubset(by_internal), "protected products missing in live snapshot")
    baseline = {}
    for r in baseline_rows:
        oid = (r.get("offer_id") or "").strip()
        if oid:
            code = norm(r.get("article"))
            require(oid not in baseline or baseline[oid] == code,
                    "conflicting article for baseline import ID")
            baseline[oid] = code
    output, checked = [], set()
    for c in candidates:
        require(isinstance(c, dict), "invalid candidate")
        oid = str(c.get("offer_id", "")).strip()
        supplier = c.get("supplier")
        n = c.get("consecutive_fresh_absences")
        require(oid in history and oid not in checked, "candidate duplicated/not in history")
        checked.add(oid)
        match = re.match(r"^c([1-5])_", str(history[oid]))
        require(match is not None and SUPPLIERS[match.group(1)] == supplier,
                "candidate supplier mismatch")
        require(type(n) is int and n >= 3 and streak.get(oid) == n,
                "candidate missing streak mismatch")
        s = suppliers[supplier]
        require(s.get("source") == "fresh" and s.get("status") == "checked",
                "candidate supplier was frozen or cached")
        require(type(s.get("limit")) is int and
                type(s.get("newly_missing")) is int and
                s["newly_missing"] <= s["limit"], "supplier absence threshold exceeded")
        require(oid not in feed_ids, "candidate still present in published XML")
        matches = by_import.get(oid, [])
        if not matches:
            output.append(dict(prom_internal_id="", import_id=oid, sku="", status="",
                               presence="", supplier=supplier, missing_streak=n,
                               assessment="not_in_prom_snapshot",
                               reason="No exact import ID in live snapshot"))
            continue
        for row in matches:
            rid, sku = row["prom_internal_id"].strip(), norm(row.get("sku"))
            assessment, why = "review_only", "Exact, unique import ID; cross-check passed"
            if len(matches) != 1:
                assessment, why = "blocked", "Non-unique import ID in live Prom snapshot"
            elif rid in manual_internal or oid in manual_import or sku in manual_sku:
                assessment, why = "blocked", "Matches protected manual ID or SKU"
            elif not sku or not baseline.get(oid):
                assessment, why = "needs_identity_review", "No verified historical SKU baseline"
            elif sku != baseline[oid]:
                assessment, why = "blocked", "Current SKU differs from historical Prom SKU"
            output.append(dict(prom_internal_id=rid, import_id=oid,
                               sku=row.get("sku", ""), status=row.get("status", ""),
                               presence=row.get("presence", ""), supplier=supplier,
                               missing_streak=n, assessment=assessment, reason=why))
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("state", "report", "feed", "snapshot", "protected", "baseline", "output"):
        p.add_argument("--" + arg, required=True)
    p.add_argument("--snapshot-max-age-hours", type=int, default=6)
    a = p.parse_args()
    require(0 < a.snapshot_max_age_hours <= 24, "invalid snapshot freshness interval")
    snapshot = Path(a.snapshot)
    age = (datetime.now(timezone.utc).timestamp() - snapshot.stat().st_mtime) / 3600
    require(-0.1 <= age <= a.snapshot_max_age_hours,
            "snapshot is too old; obtain a new GET-only snapshot")
    columns, sr = read_csv(snapshot)
    require({"prom_internal_id", "import_id", "sku", "status", "presence"}.issubset(columns),
            "missing snapshot columns")
    columns, manual = read_csv(a.protected, ";")
    require({"prom_internal_id", "prom_import_id", "sku", "protect"}.issubset(columns),
            "wrong manual registry columns")
    columns, baseline = read_csv(a.baseline)
    require({"offer_id", "article"}.issubset(columns), "wrong baseline columns")
    state = json.loads(Path(a.state).read_text(encoding="utf-8-sig"))
    report = json.loads(Path(a.report).read_text(encoding="utf-8-sig"))
    plan = make_plan(state, report, read_feed(a.feed), sr, manual, baseline)
    out = Path(a.output)
    require(not out.exists(), "refusing to overwrite plan")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(plan)
    print("MODE: READ_ONLY_REVIEW_PLAN; NO API CALLS OR STATUS UPDATES")
    print("Snapshot items:", len(sr), "Protected items:", len(manual))
    print("Observer candidates:", report["candidate_review_only"])
    print("Assessments:", dict(Counter(r["assessment"] for r in plan)))
    print("Saved local review file:", out)
    print("IMPORTANT: review_only does NOT authorize hiding.")


if __name__ == "__main__":
    main()
