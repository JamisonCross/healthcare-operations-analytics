import numpy as np
from fastapi.testclient import TestClient

from app import create_app
from operations import diagnostics


def test_capacity_cap_ties_and_outcome_independence():
    probabilities = np.array([0.5, 0.5, 0.9, 0.2, 0.1, 0.8, 0.3, 0.6, 0.7, 0.4])
    ids = np.array(["B", "A", "C", "D", "E", "F", "G", "H", "I", "J"])
    y = np.array([0, 1, 1, 0, 0, 1, 0, 0, 1, 0])
    report = diagnostics(y, probabilities, y, probabilities, ids)
    alternate = diagnostics(y, probabilities, 1 - y, probabilities, ids)
    for current, other in zip(report["capacity_scenarios"], alternate["capacity_scenarios"]):
        assert (
            len(current["selected_ids"])
            == current["slots"]
            == len(ids) * current["capacity_percent"] // 100
        )
        assert current["selected_ids"] == other["selected_ids"]
    assert sum(r["count"] for r in report["holdout_risk_histogram"]) == len(ids)
    assert report["validation_curve"] == alternate["validation_curve"]
    assert report["capacity_scenarios"][3]["selected_ids"] == ["C", "F"]
    tied = diagnostics(y, probabilities, y, np.full(10, 0.5), ids)
    assert tied["capacity_scenarios"][3]["selected_ids"] == ["A", "B"]


def test_stale_report_without_database_returns_clear_setup_error(tmp_path):
    (tmp_path / "report.json").write_text('{"synthetic":true}')
    c = TestClient(create_app(tmp_path))
    response = c.get("/api/appointments")
    assert response.status_code == 503
    assert "pipeline.py" in response.json()["detail"]
    assert not (tmp_path / "appointments.sqlite").exists()
