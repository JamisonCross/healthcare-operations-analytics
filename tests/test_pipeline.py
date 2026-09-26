import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from pipeline import FEATURES, clean_data, evaluate, generate, run


def test_reproducible_data_and_quarantine():
    raw = generate()
    pd.testing.assert_frame_equal(raw, generate())
    clean, bad, q = clean_data(raw)
    assert q["input_rows"] == 3610 and len(clean) == 3597 and len(bad) == 13
    assert clean.appointment_id.is_unique
    assert not clean.appointment_date.isna().any()
    assert clean.loc[clean.no_show == 1, "wait_minutes"].isna().all()
    assert clean.loc[clean.no_show == 0, "wait_minutes"].ge(0).all()
    assert "invalid date" in " ".join(bad.rejection_reason)
    assert "Unknown" in set(clean.age_group)


def test_inconsistent_outcomes_and_malformed_input():
    raw = generate().head(50).copy()
    raw.loc[20, "no_show"] = 1
    raw.loc[20, "outcome"] = "Completed"
    _, bad, _ = clean_data(raw)
    assert "inconsistent outcome" in " ".join(bad.rejection_reason)
    with pytest.raises(ValueError):
        clean_data(pd.DataFrame({"x": [1]}))


def test_temporal_holdout_and_no_leakage():
    clean, _, _ = clean_data(generate())
    report, scored = evaluate(clean)
    assert not set(FEATURES) & {"outcome", "wait_minutes", "no_show", "appointment_id"}
    assert scored.appointment_date.min() >= "2025-11-01"
    assert sum(v["rows"] for v in report["split"].values()) == len(clean)
    assert 0 <= report["model_metrics"]["roc_auc"] <= 1
    assert report["baseline_metrics"]["roc_auc"] == 0.5
    assert scored.no_show_probability.between(0, 1).all()
    # Changing post-visit wait times must not change predictions.
    altered = clean.copy()
    altered["wait_minutes"] = 999
    _, other = evaluate(altered)
    np.testing.assert_array_equal(scored.no_show_probability, other.no_show_probability)


def test_end_to_end_sql_and_report(tmp_path):
    report = run(tmp_path)
    with sqlite3.connect(tmp_path / "appointments.sqlite") as c:
        n, rate, wait = c.execute(
            "SELECT COUNT(*),AVG(no_show),AVG(wait_minutes) FROM appointments"
        ).fetchone()
    assert report["summary"] == {
        "appointments": n,
        "no_show_rate": round(rate, 4),
        "mean_wait_minutes": round(wait, 2),
    }
    assert len(report["findings"]) == 3
    assert sum(r["appointments"] for r in report["by_type"]) == n
    assert json.loads((tmp_path / "report.json").read_text())["synthetic"] is True


def test_sql_api_filters_and_injection(tmp_path):
    from fastapi.testclient import TestClient

    from app import create_app

    run(tmp_path)
    c = TestClient(create_app(tmp_path))
    a = c.get("/api/appointments", params={"provider": "Provider A"}).json()
    assert a["summary"]["appointments"] > 0
    assert all(r["provider"] == "Provider A" for r in a["rows"])
    assert (
        c.get("/api/appointments", params={"provider": "' OR 1=1 --"}).json()["summary"][
            "appointments"
        ]
        == 0
    )
    assert c.get("/api/appointments", params={"limit": 100000}).status_code == 422
