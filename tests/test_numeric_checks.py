import csv

from app.services import score_evidence as se


def task(case):
    return next(r for r in csv.DictReader(open("data/tasks.csv")) if r["case_id"] == case)


def test_inventory_shortfall_is_calculated_and_matched_to_answer():
    checks = se.numeric_checks(
        task("FD-002"), "P1需计提470万元；库存商品需计提80万元；合计应计提550万元，计提不足230万元。"
    )
    assert all(row["status"] == "match" for row in checks)
    assert checks[-1]["expected"] == 230
    assert checks[-1]["quote"] in "P1需计提470万元；库存商品需计提80万元；合计应计提550万元，计提不足230万元。"


def test_wrong_ratio_detected_and_missing_ratio_unknown():
    checks = se.numeric_checks(task("FD-001"), "收入增长50%，应收账款增长70%。")
    assert checks[0]["status"] == "match"
    assert checks[1]["status"] == "mismatch"
    assert checks[-1]["status"] == "unknown"


def test_changed_context_disables_fixed_calculation_rules():
    original = task("FD-002")
    original["context"] = original["context"].replace("650", "700")
    checks = se.numeric_checks(original, "计提不足230万元。")
    assert checks[0]["status"] == "not_applicable"


def test_ambiguous_repeated_values_do_not_claim_verified():
    checks = se.numeric_checks(task("FD-002"), "计提不足230万元，计提不足200万元。")
    assert checks[-1]["status"] == "unknown"
