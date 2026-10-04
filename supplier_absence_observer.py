#!/usr/bin/env python3
# coding: utf-8
"""Read-only supplier absence observer. NO Prom.ua API calls or status updates.

Produces a *proposed* next state file and an audit report. Only a successfully
finished GitHub Pages deployment should commit the proposed state to Git.
Do not use the reported candidates as an automatic hide instruction.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SUPPLIERS = {
    "1": "SANDI",
    "2": "VALESO",
    "3": "RS4U",
    "4": "B2B-SKLAD",
    "5": "OL Infrastructure",
}
SCHEMA = "supplier_absence_state_v1"
OBSERVATIONS_SCHEMA = "supplier_observations_v1"
CONFIRMATIONS_FOR_REVIEW = 3  # Reports ONLY; does not hide anything.
MAX_MISSING_ABSOLUTE = 20
MAX_MISSING_FRACTION = 0.02


def supplier_from_category(category: str) -> str:
    match = re.match(r"^c([1-5])_", str(category))
    if match is None:
        raise ValueError(f"Unknown supplier category prefix: {category!r}")
    return match.group(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(result, dict), f"Expected JSON object: {path}")
    return result


def read_published_feed(path: Path) -> dict[str, str]:
    offers = {}
    for _, item in ET.iterparse(path, events=("end",)):
        if item.tag != "offer":
            continue
        oid = (item.get("id") or "").strip()
        category = (item.findtext("categoryId") or "").strip()
        require(bool(oid) and oid not in offers,
                f"Empty or duplicate offer ID in final feed: {oid!r}")
        supplier_from_category(category)
        offers[oid] = category
        item.clear()
    require(bool(offers), "Final feed is empty")
    return offers


def evaluate(state: dict, summary: dict, observations: dict,
             final_ids: dict[str, str], run_id: str, run_number: int):
    require(state.get("schema") == SCHEMA, "Unexpected state schema")
    categories = state.get("last_known_category_by_id")
    require(isinstance(categories, dict) and bool(categories),
            "History categories missing")
    require(len(categories) == state.get("historical_ids_count"),
            "Historical ID count disagrees with category map")
    require(all(isinstance(i, str) and bool(i) for i in categories),
            "Invalid historical ID")
    require(all(isinstance(c, str) for c in categories.values()),
            "Invalid category in history")
    for category in categories.values():
        supplier_from_category(category)

    missing_streak = state.get("missing_streak")
    processed = state.get("processed_generation_ids")
    require(isinstance(missing_streak, dict) and isinstance(processed, list),
            "Invalid counter or processed runs")
    require(all(i in categories and type(n) is int and n > 0
                for i, n in missing_streak.items()), "Invalid streak entries")
    require(all(str(x).isdigit() for x in processed),
            "Invalid processed generation identifiers")
    require(len(set(map(str, processed))) == len(processed),
            "Duplicate processed run identifiers")
    baseline = state.get("baseline_workflow_run_number")
    require(type(baseline) is int and baseline >= 1,
            "Missing baseline workflow run number")
    require(str(state.get("baseline_workflow_run_id", "")).isdigit(),
            "Missing baseline workflow run ID")
    require(run_id.isdigit() and run_number > 0, "Invalid run identity")
    latest = state.get("last_processed_workflow_run_number", baseline)
    require(type(latest) is int and latest >= baseline,
            "Invalid last processed workflow run number")

    if run_number <= latest or run_id in set(map(str, processed)):
        return dict(state), {
            "mode": "READ_ONLY_DRY_RUN",
            "run_id": run_id, "run_number": run_number,
            "skipped": True, "reason": "Baseline, older, or already processed run",
            "candidate_review_only": 0, "no_prom_api_calls": True,
        }

    require(observations.get("schema") == OBSERVATIONS_SCHEMA,
            "Missing or incompatible supplier observations")
    observed = observations.get("suppliers")
    reported = summary.get("suppliers")
    require(isinstance(observed, dict) and isinstance(reported, dict),
            "Missing supplier metadata")
    require(set(observed) == set(SUPPLIERS), "Incomplete supplier observations")
    require(set(reported) == set(SUPPLIERS.values()),
            "Incomplete supplier summary")
    require(summary.get("output_offers") == len(final_ids),
            "Final XML offer count differs from generator summary")

    by_supplier = {s: set() for s in SUPPLIERS}
    for oid, category in categories.items():
        by_supplier[supplier_from_category(category)].add(oid)

    final_by_supplier = {s: set() for s in SUPPLIERS}
    for oid, category in final_ids.items():
        number = supplier_from_category(category)
        if oid in categories:
            require(supplier_from_category(categories[oid]) == number,
                    f"Supplier identity changed for offer {oid}")
        final_by_supplier[number].add(oid)

    new_categories = dict(categories)
    next_streak = dict(missing_streak)
    supplier_report = {}
    candidates = []

    for number, name in SUPPLIERS.items():
        o = observed[number]
        r = reported[name]
        require(isinstance(o, dict) and isinstance(r, dict),
                f"Invalid metadata for {name}")
        source = o.get("source")
        require(source in ("fresh", "previous") and source == r.get("source"),
                f"Supplier status mismatch for {name}")
        raw = o.get("raw_offer_ids")
        require(isinstance(raw, list), f"Raw observation missing for {name}")
        require(len(raw) == len(set(raw)) and all(isinstance(i, str) and i for i in raw),
                f"Duplicate or empty raw source IDs: {name}")
        raw_set = set(raw)
        if source == "previous":
            require(not raw, f"Cached supplier cannot claim fresh IDs: {name}")
            supplier_report[name] = {
                "source": "previous", "status": "frozen_cache",
                "checked": 0, "newly_missing": 0, "ready_for_review": 0,
            }
            continue
        require(bool(raw), f"Empty fresh supplier: {name}")
        require(o.get("raw_offer_count") == len(raw),
                f"Incorrect raw count: {name}")
        require(final_by_supplier[number].issubset(raw_set),
                f"Published products absent from supplier observations: {name}")
        require(r.get("offers", 0) <= len(raw),
                f"Filtered count exceeds source count: {name}")
        # A raw supplier may contain IDs that were removed due to price or
        # duplicate article; those are still PRESENT and never marked missing.
        historical = by_supplier[number]
        absent = historical - raw_set
        # Unusual shrinkage -> freeze supplier counters, never generate candidates.
        cap = max(MAX_MISSING_ABSOLUTE,
                  math.ceil(len(historical) * MAX_MISSING_FRACTION))
        if len(absent) > cap:
            supplier_report[name] = {
                "source": "fresh", "status": "frozen_mass_absence",
                "checked": len(historical), "newly_missing": len(absent),
                "limit": cap, "ready_for_review": 0,
            }
            continue
        for oid in historical:
            if oid in raw_set:
                next_streak.pop(oid, None)
            else:
                next_streak[oid] = next_streak.get(oid, 0) + 1
                if next_streak[oid] >= CONFIRMATIONS_FOR_REVIEW:
                    candidates.append({
                        "offer_id": oid, "supplier": name,
                        "consecutive_fresh_absences": next_streak[oid],
                    })
        # Track new supplier products only after they were accepted into the
        # validated, categorized final XML (not merely seen in a source feed).
        for oid in final_by_supplier[number] - historical:
            new_categories[oid] = final_ids[oid]
        supplier_report[name] = {
            "source": "fresh", "status": "checked",
            "checked": len(historical), "newly_missing": len(absent),
            "limit": cap,
            "added_to_history": len(final_by_supplier[number] - historical),
            "ready_for_review": sum(c["supplier"] == name for c in candidates),
        }

    # Never delete historic IDs. Do not touch Prom or act on candidates.
    result = dict(state)
    result["last_known_category_by_id"] = new_categories
    result["historical_ids_count"] = len(new_categories)
    result["missing_streak"] = next_streak
    result["processed_generation_ids"] = processed + [run_id]
    result["last_processed_workflow_run_number"] = run_number
    result["last_processed_workflow_run_id"] = run_id
    report = {
        "mode": "READ_ONLY_DRY_RUN", "run_id": run_id,
        "run_number": run_number, "skipped": False,
        "suppliers": supplier_report,
        "historical_ids": len(new_categories),
        "active_missing_streaks": len(next_streak),
        "candidate_review_only": len(candidates),
        "candidates_for_manual_review": sorted(candidates, key=lambda x: (x["supplier"], x["offer_id"])),
        "no_prom_api_calls": True,
        "note": "Candidates are NOT hide instructions. Require up-to-date Prom snapshot,"
                " internal-ID matching and protected-59 exclusions before any API change.",
    }
    return result, report


def write_json_atomic(path: Path, value: dict):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="supplier_absence_state.json")
    p.add_argument("--summary", default="merge_summary_test.json")
    p.add_argument("--observations", default="supplier_observations_test.json")
    p.add_argument("--feed", default="merged_prom_catalog_test.xml")
    p.add_argument("--output-state", default="supplier_absence_next_state.json")
    p.add_argument("--report", default="supplier_absence_report.json")
    p.add_argument("--run-id", required=True)
    p.add_argument("--run-number", type=int, required=True)
    args = p.parse_args()
    require(Path(args.state).resolve() != Path(args.output_state).resolve(),
            "Input state and proposed state must have different paths")
    state, report = evaluate(
        load_json(Path(args.state)), load_json(Path(args.summary)),
        load_json(Path(args.observations)), read_published_feed(Path(args.feed)),
        args.run_id, args.run_number,
    )
    write_json_atomic(Path(args.output_state), state)
    write_json_atomic(Path(args.report), report)
    print(json.dumps({k: v for k, v in report.items()
                      if k != "candidates_for_manual_review"},
                     ensure_ascii=False, indent=2))
    print("DRY-RUN: no Prom.ua requests and no status updates.")


if __name__ == "__main__":
    main()
