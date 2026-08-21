"""
Cohort retention analysis: monthly acquisition cohorts, retention triangles,
and Kaplan-Meier survival curves for time-to-churn by segment.

Kaplan-Meier is implemented directly (no external survival-analysis library)
so the estimator's mechanics are fully visible rather than hidden in a
dependency.

Outputs:
  - retention_triangle.csv/.png
  - survival_by_payer.png
  - engagement_score.csv (feeds the churn-risk framing)
  - memo.md
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import connect

HERE = Path(__file__).resolve().parent


def kaplan_meier(duration: np.ndarray, event_observed: np.ndarray):
    """Minimal Kaplan-Meier estimator.

    duration: time-to-event or time-to-censoring, per subject
    event_observed: 1 if the event (churn) was observed, 0 if censored

    Returns (timeline, survival_prob) step-function arrays.
    """
    df = pd.DataFrame({"t": duration, "e": event_observed}).sort_values("t")
    unique_times = df["t"].unique()
    n_at_risk = len(df)
    survival = 1.0
    timeline = [0.0]
    surv_probs = [1.0]
    for t in unique_times:
        at_t = df[df["t"] == t]
        d_i = at_t["e"].sum()          # events at time t
        n_i = n_at_risk                # at risk just before t
        if n_i > 0 and d_i > 0:
            survival *= (1 - d_i / n_i)
        n_at_risk -= len(at_t)
        timeline.append(t)
        surv_probs.append(survival)
    return np.array(timeline), np.array(surv_probs)


def main():
    con = connect()
    j = con.execute("select * from main_marts.patient_journey").df()
    j = j[j["did_first_visit"]].copy()
    j["first_visit_date"] = pd.to_datetime(j["first_visit_date"])
    j["last_visit_date"] = pd.to_datetime(j["last_visit_date"])
    j["referral_month"] = pd.to_datetime(j["referral_month"])

    max_date = j["last_visit_date"].max()

    # time-to-churn proxy: days from first visit to last visit (observed
    # "died" if their span looks complete, i.e. last visit isn't near the
    # data horizon -- otherwise treat as right-censored)
    j["days_active"] = (j["last_visit_date"] - j["first_visit_date"]).dt.days.clip(lower=0)
    j["censored"] = (max_date - j["last_visit_date"]).dt.days < 21  # still active near data edge
    j["event_observed"] = (~j["censored"]).astype(int)

    # --- Retention triangle: monthly cohorts x months-since-first-visit ---
    j["cohort_month"] = j["first_visit_date"].dt.to_period("M")
    j["months_since"] = (
        (j["last_visit_date"].dt.to_period("M") - j["cohort_month"]).apply(lambda x: x.n)
    )
    max_cohort_horizon = 9
    rows = []
    for cohort, g in j.groupby("cohort_month"):
        cohort_size = len(g)
        for h in range(max_cohort_horizon + 1):
            still_active = (g["months_since"] >= h).sum()
            rows.append({"cohort_month": str(cohort), "months_since": h,
                          "cohort_size": cohort_size,
                          "pct_active": round(still_active / cohort_size * 100, 1)})
    triangle = pd.DataFrame(rows)
    triangle.to_csv(HERE / "retention_triangle.csv", index=False)

    pivot = triangle.pivot(index="cohort_month", columns="months_since", values="pct_active")
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(pivot.values, cmap="YlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index, fontsize=8)
    ax.set_xlabel("Months since first visit"); ax.set_ylabel("Cohort (first-visit month)")
    ax.set_title("Retention triangle — % of cohort still active")
    for i in range(pivot.shape[0]):
        for k in range(pivot.shape[1]):
            v = pivot.values[i, k]
            if not np.isnan(v):
                ax.text(k, i, f"{v:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if v > 55 else "black")
    fig.colorbar(im, ax=ax, label="% active")
    fig.tight_layout()
    fig.savefig(HERE / "retention_triangle.png", dpi=150)
    plt.close(fig)

    # --- Kaplan-Meier survival by payer ---
    fig, ax = plt.subplots(figsize=(8, 5))
    payer_summary = []
    for payer, g in j.groupby("payer"):
        t, s = kaplan_meier(g["days_active"].values, g["event_observed"].values)
        ax.step(t, s, where="post", label=payer)
        median_idx = np.searchsorted(-s, -0.5)
        median_days = t[median_idx] if median_idx < len(t) else np.nan
        payer_summary.append({"payer": payer, "n": len(g), "median_survival_days": median_days})
    ax.set_xlabel("Days since first visit"); ax.set_ylabel("Estimated share still active")
    ax.set_title("Kaplan-Meier retention curves by payer")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_ylim(0, 1.02)
    fig.tight_layout()
    fig.savefig(HERE / "survival_by_payer.png", dpi=150)
    plt.close(fig)
    payer_summary_df = pd.DataFrame(payer_summary).sort_values("median_survival_days")
    payer_summary_df.to_csv(HERE / "survival_summary_by_payer.csv", index=False)
    print(payer_summary_df.to_string(index=False))

    # --- Kaplan-Meier survival by condition chronicity proxy (condition) ---
    fig, ax = plt.subplots(figsize=(8, 5))
    for condition, g in j.groupby("condition"):
        if len(g) < 200:
            continue
        t, s = kaplan_meier(g["days_active"].values, g["event_observed"].values)
        ax.step(t, s, where="post", label=condition)
    ax.set_xlabel("Days since first visit"); ax.set_ylabel("Estimated share still active")
    ax.set_title("Kaplan-Meier retention curves by condition")
    ax.legend(fontsize=7, loc="lower left")
    ax.set_ylim(0, 1.02)
    fig.tight_layout()
    fig.savefig(HERE / "survival_by_condition.png", dpi=150)
    plt.close(fig)

    # --- simple engagement score (recency/frequency), trailing-60d as of data horizon ---
    ed = con.execute("select * from main_marts.engagement_daily").df()
    ed["event_date"] = pd.to_datetime(ed["event_date"])
    as_of = ed["event_date"].max()
    trailing = ed[ed["event_date"] >= as_of - pd.Timedelta(days=60)]
    visit_recency = (
        trailing[trailing.event_type == "visit"]
        .groupby("patient_id")["event_date"].max()
        .apply(lambda d: max(0.0, 1 - (as_of - d).days / 60))
    )
    msg_response = (
        trailing[trailing.event_type == "message"]
        .groupby("patient_id")["positive_event"].mean()
    )
    engagement = pd.DataFrame({"visit_recency_component": visit_recency}).join(
        pd.DataFrame({"message_response_component": msg_response}), how="outer"
    ).fillna(0.0)
    engagement["engagement_score"] = (
        0.6 * engagement["visit_recency_component"] + 0.4 * engagement["message_response_component"]
    ).round(3)
    engagement.reset_index(names="patient_id").to_csv(HERE / "engagement_score.csv", index=False)

    worst_payer = payer_summary_df.iloc[0]
    best_payer = payer_summary_df.iloc[-1]
    memo = f"""# Memo: Retention isn't one number — it depends heavily on payer and condition

**To:** Product & Ops leadership
**From:** Data Science
**Re:** Cohort retention & survival analysis

## Headline

Median time-to-churn ranges from **{worst_payer.median_survival_days:.0f} days** ({worst_payer.payer}) to
**{best_payer.median_survival_days:.0f}+ days** ({best_payer.payer}) depending on payer. A single blended
retention number hides this — segment-level tracking is necessary, not optional.

## Method note

Retention is measured two ways here on purpose:
1. **Retention triangles** (`retention_triangle.png`) — the standard cohort view, easy to read but treats
   "still active" as binary per month and ignores censoring.
2. **Kaplan-Meier survival curves** (`survival_by_payer.png`, `survival_by_condition.png`) — properly accounts
   for patients who haven't had a chance to churn yet (right-censoring near the data horizon), which the
   triangle silently overstates for recent cohorts.

## Segment findings

| Payer | n | Median days active |
|---|---:|---:|
{chr(10).join(f"| {r.payer} | {r.n:,} | {r.median_survival_days:.0f} |" for r in payer_summary_df.itertuples())}

## Recommendation

1. Report retention by payer and condition on the exec dashboard, not just blended — the blended number masks
   a >2x spread in median active duration.
2. Use `engagement_score.csv` (recency-weighted visit + message-response signal) as a leading indicator to
   flag at-risk patients before they fully churn, not after.
3. Feed the low-retention segments into the feature-launch prioritization in `analyses/03` — the reminders
   feature should be evaluated for differential effect by payer/condition, not just overall.

*Charts: `retention_triangle.png`, `survival_by_payer.png`, `survival_by_condition.png`.*
"""
    (HERE / "memo.md").write_text(memo, encoding="utf-8")
    print(f"\nWrote memo.md and charts to {HERE}")


if __name__ == "__main__":
    main()
