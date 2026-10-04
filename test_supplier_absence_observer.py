"""Standalone synthetic tests; never call GitHub, suppliers or Prom.ua."""
import unittest

from supplier_absence_observer import evaluate


NAMES = {
    "1": "SANDI", "2": "VALESO", "3": "RS4U",
    "4": "B2B-SKLAD", "5": "OL Infrastructure",
}


def fixtures(amount=2):
    categories = {f"p{k}_{i}": f"c{k}_g" for k in NAMES for i in range(amount)}
    state = {
        "schema": "supplier_absence_state_v1", "historical_ids_count": len(categories),
        "last_known_category_by_id": categories,
        "missing_streak": {}, "processed_generation_ids": [],
        "baseline_workflow_run_number": 21,
        "baseline_workflow_run_id": 37232728103,
    }
    obs = {
        "schema": "supplier_observations_v1",
        "suppliers": {
            k: {"name": name, "source": "fresh", "raw_offer_ids": [f"p{k}_{i}" for i in range(amount)], "raw_offer_count": amount}
            for k, name in NAMES.items()
        },
    }
    final = dict(categories)
    summary = {
        "output_offers": len(final),
        "suppliers": {name: {"source": "fresh", "offers": amount} for name in NAMES.values()},
    }
    return state, summary, obs, final


def rerun(state, summary, obs, final, number):
    return evaluate(state, summary, obs, final, str(888000 + number), number)


class SafetyTests(unittest.TestCase):
    def test_baseline_not_processed(self):
        state, summary, obs, final = fixtures()
        next_state, report = rerun(state, summary, obs, final, 21)
        self.assertTrue(report["skipped"])
        self.assertEqual(next_state, state)

    def test_missing_confirmations_and_duplicate_run(self):
        state, summary, obs, final = fixtures()
        obs["suppliers"]["1"]["raw_offer_ids"].remove("p1_0")
        obs["suppliers"]["1"]["raw_offer_count"] -= 1
        final.pop("p1_0")
        summary["output_offers"] -= 1
        summary["suppliers"]["SANDI"]["offers"] -= 1
        for n in (22, 23, 24):
            state, report = rerun(state, summary, obs, final, n)
            self.assertEqual(state["missing_streak"]["p1_0"], n - 21)
        self.assertEqual(report["candidate_review_only"], 1)
        before = state.copy()
        state, report = rerun(state, summary, obs, final, 24)
        self.assertTrue(report["skipped"])
        self.assertEqual(before, state)

    def test_cache_does_not_increment_or_clear(self):
        state, summary, obs, final = fixtures()
        state["missing_streak"] = {"p1_0": 1}
        obs["suppliers"]["1"].update(source="previous", raw_offer_ids=[], raw_offer_count=0)
        summary["suppliers"]["SANDI"]["source"] = "previous"
        state, report = rerun(state, summary, obs, final, 22)
        self.assertEqual(state["missing_streak"]["p1_0"], 1)
        self.assertEqual(report["suppliers"]["SANDI"]["status"], "frozen_cache")

    def test_reappear_resets_streak(self):
        state, summary, obs, final = fixtures()
        state["missing_streak"] = {"p1_0": 2}
        state, _ = rerun(state, summary, obs, final, 22)
        self.assertNotIn("p1_0", state["missing_streak"])

    def test_supplier_filter_excludes_from_final_but_is_present(self):
        state, summary, obs, final = fixtures()
        final.pop("p1_0")  # Price or article filtered, but raw XML still has ID.
        summary["output_offers"] -= 1
        summary["suppliers"]["SANDI"]["offers"] = 1
        state, report = rerun(state, summary, obs, final, 22)
        self.assertEqual(report["candidate_review_only"], 0)
        self.assertNotIn("p1_0", state["missing_streak"])

    def test_mass_absence_freezes_supplier(self):
        state, summary, obs, final = fixtures(amount=50)
        missing = {f"p1_{i}" for i in range(25)}
        obs["suppliers"]["1"]["raw_offer_ids"] = [x for x in obs["suppliers"]["1"]["raw_offer_ids"] if x not in missing]
        obs["suppliers"]["1"]["raw_offer_count"] = 25
        summary["suppliers"]["SANDI"]["offers"] = 25
        for oid in missing:
            final.pop(oid)
        summary["output_offers"] = len(final)
        state, report = rerun(state, summary, obs, final, 22)
        self.assertEqual(report["suppliers"]["SANDI"]["status"], "frozen_mass_absence")
        self.assertFalse(state["missing_streak"])

    def test_new_accepted_product_added_to_history(self):
        state, summary, obs, final = fixtures()
        obs["suppliers"]["2"]["raw_offer_ids"].append("new2")
        obs["suppliers"]["2"]["raw_offer_count"] += 1
        final["new2"] = "c2_new"
        summary["suppliers"]["VALESO"]["offers"] += 1
        summary["output_offers"] += 1
        state, report = rerun(state, summary, obs, final, 22)
        self.assertEqual(state["last_known_category_by_id"]["new2"], "c2_new")
        self.assertEqual(report["suppliers"]["VALESO"]["added_to_history"], 1)

    def test_cross_supplier_change_refused(self):
        state, summary, obs, final = fixtures()
        final["p1_0"] = "c2_wrong"
        with self.assertRaisesRegex(ValueError, "Supplier identity changed"):
            rerun(state, summary, obs, final, 22)

    def test_invalid_manifest_refused(self):
        state, summary, obs, final = fixtures()
        obs["suppliers"]["1"]["raw_offer_ids"].append("p1_0")
        obs["suppliers"]["1"]["raw_offer_count"] += 1
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rerun(state, summary, obs, final, 22)


if __name__ == "__main__":
    unittest.main(verbosity=2)
