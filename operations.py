"""Operational diagnostics; no threshold fitting or intervention-effect claims."""

import numpy as np
from sklearn.metrics import precision_score, recall_score


def diagnostics(validation_y, validation_prob, test_y, test_prob, test_ids):
    curve = []
    for threshold in np.linspace(0, 1, 21):
        selected = validation_prob >= threshold
        curve.append(
            {
                "threshold": round(float(threshold), 2),
                "precision": round(
                    float(precision_score(validation_y, selected, zero_division=0)), 4
                ),
                "recall": round(float(recall_score(validation_y, selected, zero_division=0)), 4),
                "flagged_fraction": round(float(selected.mean()), 4),
                "flagged": int(selected.sum()),
            }
        )
    counts, edges = np.histogram(test_prob, bins=np.linspace(0, 1, 11))
    histogram = [
        {
            "from": round(float(edges[i]), 1),
            "to": round(float(edges[i + 1]), 1),
            "count": int(count),
        }
        for i, count in enumerate(counts)
    ]
    # Deterministic ID tie-break; rank uses only probability, never holdout outcomes.
    order = np.lexsort((np.asarray(test_ids), -test_prob))
    outcomes = np.asarray(test_y)
    scenarios = []
    for capacity in [5, 10, 15, 20, 25, 30, 40]:
        slots = int(len(test_prob) * capacity // 100)
        chosen = order[:slots]
        captured = int(outcomes[chosen].sum())
        random_expected = slots * float(outcomes.mean())
        scenarios.append(
            {
                "capacity_percent": capacity,
                "slots": slots,
                "cohort_size": len(test_prob),
                "captured_no_shows": captured,
                "total_no_shows": int(outcomes.sum()),
                "precision": captured / slots if slots else 0,
                "recall": captured / int(outcomes.sum()) if outcomes.sum() else 0,
                "random_expected_captured": round(random_expected, 2),
                "lift_over_random": captured / random_expected if random_expected else None,
                "selected_ids": [str(test_ids[i]) for i in chosen],
            }
        )
    return {
        "validation_curve": curve,
        "holdout_risk_histogram": histogram,
        "capacity_scenarios": scenarios,
        "capacity_method": "Retrospective ranking of the entire Nov–Dec holdout. At most floor(capacity × visits) slots, ties broken by appointment ID. Outcomes only evaluate the selected queue. This is cohort capacity, not a daily staffing forecast. No claims about prevented no-shows or causal reminder benefit.",
    }
