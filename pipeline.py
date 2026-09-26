"""Reproducible synthetic-data study. Never trains on real patient information."""

import argparse
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from operations import diagnostics

ROOT = Path(__file__).parent
NUMERIC = ["lead_days", "prior_no_shows", "reminder_sent", "appointment_hour"]
CATEGORICAL = ["appointment_type", "provider", "age_group"]
FEATURES = NUMERIC + CATEGORICAL
TYPES = ["Primary care", "Behavioral health", "Follow-up", "Specialty"]
AGES = ["18–34", "35–49", "50–64", "65+"]
PROVIDERS = ["Provider A", "Provider B", "Provider C", "Provider D"]


def generate(seed=42, n=3600):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        dt = pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(rng.integers(0, 365)))
        kind = str(rng.choice(TYPES, p=[0.35, 0.20, 0.30, 0.15]))
        provider = str(rng.choice(PROVIDERS))
        lead = int(rng.integers(1, 46))
        prior = int(rng.choice([0, 1, 2, 3], p=[0.65, 0.23, 0.09, 0.03]))
        reminder = int(rng.random() < 0.76)
        hour = int(rng.choice([8, 9, 10, 11, 13, 14, 15, 16]))
        age = str(rng.choice(AGES))
        # Deliberately encoded associations, not findings about real people.
        logit = (
            -2.8
            + 0.037 * lead
            + 0.55 * prior
            - 0.65 * reminder
            + 0.7 * (kind == "Behavioral health")
            + 0.3 * (hour == 8)
        )
        no_show = int(rng.random() < 1 / (1 + math.exp(-logit)))
        wait = (
            None
            if no_show
            else round(
                max(
                    0,
                    rng.normal(10 + 10 * (provider == "Provider C") + 5 * (hour >= 14), 5),
                ),
                1,
            )
        )
        rows.append(
            {
                "appointment_id": f"A{i + 1:05d}",
                "appointment_date": dt.strftime("%Y-%m-%d"),
                "provider": provider,
                "appointment_type": kind,
                "age_group": age,
                "lead_days": lead,
                "prior_no_shows": prior,
                "reminder_sent": reminder,
                "appointment_hour": hour,
                "no_show": no_show,
                "wait_minutes": wait,
                "outcome": "No-show"
                if no_show
                else str(rng.choice(["Completed", "Referred"], p=[0.88, 0.12])),
            }
        )
    clean = pd.DataFrame(rows)
    # Inject known issues to make the cleaning task inspectable.
    dirty = clean.copy()
    dirty.loc[0, "provider"] = "  provider a  "
    dirty.loc[1, "appointment_type"] = " follow-up "
    dirty.loc[2, "appointment_date"] = "bad-date"
    dirty.loc[3, "wait_minutes"] = -12
    dirty.loc[4, "lead_days"] = -2
    dirty.loc[5, "age_group"] = None
    return pd.concat([dirty, dirty.iloc[10:20]], ignore_index=True)


def clean_data(raw):
    required = {
        "appointment_id",
        "appointment_date",
        "provider",
        "appointment_type",
        "age_group",
        "lead_days",
        "prior_no_shows",
        "reminder_sent",
        "appointment_hour",
        "no_show",
        "wait_minutes",
        "outcome",
    }
    if not required.issubset(raw.columns):
        raise ValueError("Missing columns: " + ", ".join(sorted(required - set(raw.columns))))
    data = raw.copy()
    data["source_row"] = np.arange(len(data)) + 2
    for col, allowed in [
        ("provider", PROVIDERS),
        ("appointment_type", TYPES),
        ("age_group", AGES),
        ("outcome", ["Completed", "Referred", "No-show"]),
    ]:
        mapping = {x.lower(): x for x in allowed}
        normalized = data[col].astype("string").str.strip().str.lower().map(mapping)
        if col == "age_group":
            normalized = normalized.fillna("Unknown")
        data[col] = normalized
    parsed = pd.to_datetime(data["appointment_date"], format="%Y-%m-%d", errors="coerce")
    data["appointment_date"] = parsed.dt.strftime("%Y-%m-%d")
    numeric = [
        "lead_days",
        "prior_no_shows",
        "reminder_sent",
        "appointment_hour",
        "no_show",
        "wait_minutes",
    ]
    for col in numeric:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    reasons = pd.Series("", index=data.index)

    def flag(mask, reason):
        nonlocal reasons
        reasons.loc[mask] = reasons.loc[mask] + reason + "; "

    flag(data["appointment_id"].duplicated(keep="first"), "duplicate appointment ID")
    flag(
        ~data["appointment_id"].astype("string").str.match(r"^A\d{5}$", na=False),
        "invalid appointment ID",
    )
    flag(parsed.isna(), "invalid date")
    flag(
        data[["provider", "appointment_type", "outcome"]].isna().any(axis=1),
        "unknown category",
    )
    for col, lo, hi in [
        ("lead_days", 0, 365),
        ("prior_no_shows", 0, 50),
        ("appointment_hour", 0, 23),
    ]:
        flag(~data[col].between(lo, hi) | (data[col] % 1 != 0), "invalid " + col)
    for col in ["no_show", "reminder_sent"]:
        flag(~data[col].isin([0, 1]), "invalid " + col)
    flag(
        (data["no_show"] == 0) & (~data["wait_minutes"].between(0, 480)),
        "invalid attended wait time",
    )
    flag((data["no_show"] == 1) & data["wait_minutes"].notna(), "no-show has wait time")
    flag(
        (data["no_show"] == 1) & (data["outcome"] != "No-show")
        | (data["no_show"] == 0) & (data["outcome"] == "No-show"),
        "inconsistent outcome",
    )
    rejected = raw.loc[reasons != ""].copy()
    rejected["source_row"] = data.loc[reasons != "", "source_row"]
    rejected["rejection_reason"] = reasons[reasons != ""].str.rstrip("; ")
    accepted = (
        data.loc[reasons == ""]
        .drop(columns="source_row")
        .sort_values(["appointment_date", "appointment_id"])
        .reset_index(drop=True)
    )
    for col in [
        "lead_days",
        "prior_no_shows",
        "reminder_sent",
        "appointment_hour",
        "no_show",
    ]:
        accepted[col] = accepted[col].astype(int)
    report = {
        "input_rows": len(raw),
        "accepted_rows": len(accepted),
        "quarantined_rows": len(rejected),
        "duplicate_rows": int(raw["appointment_id"].duplicated().sum()),
        "unknown_age_rows": int((accepted.age_group == "Unknown").sum()),
        "rules": "Normalize labels; quarantine invalid dates, ranges, inconsistent outcomes and duplicate IDs; retain missing ages as Unknown. No-show wait times remain null.",
    }
    return accepted, rejected, report


def evaluate(clean):
    # Whole calendar dates keep train, validation and holdout disjoint.
    train = clean[clean.appointment_date < "2025-09-01"]
    validation = clean[
        (clean.appointment_date >= "2025-09-01") & (clean.appointment_date < "2025-11-01")
    ]
    test = clean[clean.appointment_date >= "2025-11-01"]
    if any(len(d) < 50 or d.no_show.nunique() < 2 for d in [train, validation, test]):
        raise ValueError("Each chronological partition needs >=50 rows and both classes.")
    preprocess = ColumnTransformer(
        [
            (
                "numbers",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                NUMERIC,
            ),
            ("categories", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ]
    )
    model = Pipeline(
        [
            ("preprocess", preprocess),
            ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )
    model.fit(train[FEATURES], train.no_show)
    # Fixed capacity budget chosen in advance: about 20% of validation appointments flagged.
    val_prob = model.predict_proba(validation[FEATURES])[:, 1]
    threshold = float(np.quantile(val_prob, 0.8))
    prob = model.predict_proba(test[FEATURES])[:, 1]
    pred = (prob >= threshold).astype(int)
    baseline = DummyClassifier(strategy="prior").fit(train[FEATURES], train.no_show)
    base_prob = baseline.predict_proba(test[FEATURES])[:, 1]

    def metrics(p):
        return {
            "roc_auc": round(float(roc_auc_score(test.no_show, p)), 4),
            "average_precision": round(float(average_precision_score(test.no_show, p)), 4),
            "brier_score": round(float(brier_score_loss(test.no_show, p)), 4),
        }

    report = {
        "split": {
            "train": {"rows": len(train), "through": "2025-08-31"},
            "validation": {
                "rows": len(validation),
                "from": "2025-09-01",
                "through": "2025-10-31",
            },
            "test": {"rows": len(test), "from": "2025-11-01", "through": "2025-12-31"},
        },
        "features": FEATURES,
        "excluded_post_visit_fields": ["no_show", "wait_minutes", "outcome"],
        "model": "Logistic regression",
        "threshold": round(threshold, 6),
        "threshold_selection": "80th percentile of validation probabilities; chosen before test evaluation. Intended for supportive reminders only.",
        "model_metrics": metrics(prob),
        "baseline_metrics": metrics(base_prob),
        "test_prevalence": round(float(test.no_show.mean()), 4),
        "precision": round(float(precision_score(test.no_show, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(test.no_show, pred, zero_division=0)), 4),
        "flagged_fraction": round(float(pred.mean()), 4),
        "confusion_matrix": confusion_matrix(test.no_show, pred, labels=[0, 1]).tolist(),
        "limitations": [
            "Synthetic associations were encoded in the generator; metrics do not establish real-world validity.",
            "One unique synthetic appointment per patient; repeated-patient leakage must be controlled in real data.",
            "Features are assumed available at the day-before-visit scoring cutoff.",
            "No clinical, eligibility, scheduling-priority, or denial-of-care decisions.",
            "Subgroup comparisons here are descriptive and too limited to establish fairness.",
        ],
    }
    scored = test[["appointment_id", "appointment_date", "age_group", "no_show"]].copy()
    scored["no_show_probability"] = np.round(prob, 6)
    scored["reminder_review_flag"] = pred
    report["age_group_audit"] = [
        {
            "age_group": str(age),
            "rows": len(group),
            "observed_rate": round(float(group.no_show.mean()), 4),
            "mean_predicted": round(float(group.no_show_probability.mean()), 4),
        }
        for age, group in scored.groupby("age_group")
    ]
    names = model.named_steps["preprocess"].get_feature_names_out()
    coefficients = model.named_steps["classifier"].coef_[0]
    report["coefficients"] = [
        {"feature": str(f), "coefficient": round(float(v), 4)}
        for f, v in sorted(zip(names, coefficients), key=lambda x: abs(x[1]), reverse=True)
    ]
    report["operations"] = diagnostics(
        validation.no_show, val_prob, test.no_show, prob, test.appointment_id.to_numpy()
    )
    return report, scored


def run(output=None):
    output = Path(output or ROOT / "data")
    output.mkdir(parents=True, exist_ok=True)
    raw = generate()
    raw.to_csv(output / "appointments_raw.csv", index=False)
    clean, rejected, quality = clean_data(raw)
    clean.to_csv(output / "appointments_clean.csv", index=False)
    rejected.to_csv(output / "quarantine.csv", index=False)
    with sqlite3.connect(output / "appointments.sqlite") as conn:
        clean.to_sql("appointments", conn, index=False, if_exists="replace")
        queries = [q.strip() for q in (ROOT / "analysis.sql").read_text().split(";") if q.strip()]
        tables = [pd.read_sql_query(q, conn) for q in queries]
        by_type, by_provider, by_window = tables
        for name, table in zip(["by_type", "by_provider", "by_booking_window"], tables):
            table.to_csv(output / (name + ".csv"), index=False)
    model, scored = evaluate(clean)
    scored.to_csv(output / "test_predictions.csv", index=False)
    top = by_type.iloc[0]
    slow = by_provider.iloc[0]
    windows = by_window.set_index("booking_window")
    findings = [
        f"{top.appointment_type} has the highest synthetic no-show rate: {top.no_show_percent:.2f}% across {int(top.appointments):,} appointments. Consider testing a supportive reminder workflow; this is not a causal result.",
        f"{slow.provider} has the longest mean recorded wait: {slow.average_wait_minutes:.2f} minutes among {int(slow.attended):,} attended visits. Review slot length and workload before making staffing changes.",
        f"Appointments booked 21+ days ahead have an {windows.loc['21+ days', 'no_show_percent']:.2f}% no-show rate versus {windows.loc['Under 21 days', 'no_show_percent']:.2f}% for shorter booking windows. The relationship is deliberately encoded in this synthetic generator.",
    ]
    report = {
        "synthetic": True,
        "seed": 42,
        "quality": quality,
        "summary": {
            "appointments": len(clean),
            "no_show_rate": round(float(clean.no_show.mean()), 4),
            "mean_wait_minutes": round(float(clean.wait_minutes.mean()), 2),
        },
        "findings": findings,
        "by_type": by_type.to_dict("records"),
        "by_provider": by_provider.to_dict("records"),
        "by_booking_window": by_window.to_dict("records"),
        "model": model,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "findings.md").write_text(
        "# Synthetic appointment operations study\n\nThese results describe generated data, not a medical practice.\n\n"
        + "\n\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings))
        + "\n"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    result = run(args.output)
    print(
        json.dumps(
            {
                "quality": result["quality"],
                "model_metrics": result["model"]["model_metrics"],
            },
            indent=2,
        )
    )
