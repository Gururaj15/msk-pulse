"""
Funnel analysis: where do patients actually drop off between referral and
becoming an active, retained patient?

Stages: referred -> intake -> auth submitted -> auth approved -> first visit.

Outputs:
  - funnel_overall.png / funnel_by_payer.png
  - memo.md (plain-English write-up with a recommendation)
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import connect

HERE = Path(__file__).resolve().parent


def main():
    con = connect()
    j = con.execute("select * from main_marts.patient_journey").df()

    # exclude the last 30 days of referrals to avoid right-censoring bias
    # (patients who simply haven't had time to progress yet)
    max_date = j["referral_date"].max()
    cutoff = max_date - pd.Timedelta(days=30)
    j = j[j["referral_date"] <= cutoff].copy()

    stages = ["referred", "intake", "auth_submitted", "auth_approved", "first_visit"]
    counts = {
        "referred": len(j),
        "intake": j["did_intake"].sum(),
        "auth_submitted": j["did_submit_auth"].sum(),
        "auth_approved": (j["did_submit_auth"] & j["auth_approved"]).sum(),
        "first_visit": j["did_first_visit"].sum(),
    }
    funnel = pd.DataFrame({"stage": stages, "n": [counts[s] for s in stages]})
    funnel["pct_of_referred"] = (funnel["n"] / funnel["n"].iloc[0] * 100).round(1)
    funnel["pct_of_prior_stage"] = (
        funnel["n"] / funnel["n"].shift(1).fillna(funnel["n"].iloc[0]) * 100
    ).round(1)
    print(funnel.to_string(index=False))
    funnel.to_csv(HERE / "funnel_overall.csv", index=False)

    # --- chart: overall funnel ---
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#0E7C6B"] * len(stages)
    ax.barh(funnel["stage"][::-1], funnel["n"][::-1], color=colors)
    for i, (n, pct) in enumerate(zip(funnel["n"][::-1], funnel["pct_of_referred"][::-1])):
        ax.text(n, i, f"  {n:,}  ({pct}%)", va="center", fontsize=10)
    ax.set_xlabel("Patients")
    ax.set_title("Patient journey funnel (all clinics, all payers)")
    fig.tight_layout()
    fig.savefig(HERE / "funnel_overall.png", dpi=150)
    plt.close(fig)

    # --- drop-off by payer at the biggest leak: auth_submitted -> auth_approved ---
    by_payer = (
        j[j["did_submit_auth"]]
        .groupby("payer")
        .agg(n_submitted=("patient_id", "count"), n_approved=("auth_approved", "sum"))
        .assign(approval_rate=lambda d: (d.n_approved / d.n_submitted * 100).round(1))
        .sort_values("approval_rate")
    )
    print("\nApproval rate by payer:\n", by_payer)
    by_payer.to_csv(HERE / "approval_rate_by_payer.csv")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(by_payer.index, by_payer["approval_rate"], color="#3D5A80")
    ax.set_xlabel("Auth approval rate (%)")
    ax.set_title("Prior-auth approval rate by payer")
    ax.set_xlim(0, 100)
    fig.tight_layout()
    fig.savefig(HERE / "funnel_by_payer.png", dpi=150)
    plt.close(fig)

    # --- biggest leak identification ---
    funnel["abs_drop"] = -funnel["n"].diff()
    biggest_leak = funnel.iloc[1:].loc[funnel["abs_drop"].idxmax()]

    memo = f"""# Memo: Where MSK Pulse patients drop off

**To:** Product & Ops leadership
**From:** Data Science
**Re:** Patient journey funnel analysis

## Headline

Of {counts['referred']:,} referred patients, {counts['first_visit']:,} ({funnel.iloc[-1].pct_of_referred}%) reach a first visit.
The single largest drop-off is **{biggest_leak.stage.replace('_', ' ')}**, losing {int(biggest_leak.abs_drop):,} patients
({100 - biggest_leak.pct_of_prior_stage:.1f}% of everyone who reached the prior stage).

## The funnel

| Stage | Patients | % of referred | % of prior stage |
|---|---:|---:|---:|
{chr(10).join(f"| {r.stage.replace('_',' ')} | {r.n:,} | {r.pct_of_referred}% | {r.pct_of_prior_stage}% |" for r in funnel.itertuples())}

## Why prior auth is the stage to fix

Auth approval is the only stage in this funnel that is (a) large, (b) not a patient-behavior problem, and
(c) directly addressable with better documentation and predictive triage. Intake drop-off is largely patient
choice / scheduling; auth denial is an operational and payer-driven leak Flagler can act on directly.

Approval rate varies sharply by payer — from {by_payer.approval_rate.min()}% to {by_payer.approval_rate.max()}%
— which means payer-specific documentation requirements, not just clinical necessity, are driving a meaningful
share of denials.

## Recommendation

1. Prioritize prior-auth denial reduction as the highest-leverage funnel fix — it is the biggest lever with the
   clearest mechanism (better documentation, earlier risk flagging).
2. Build a denial-risk model to flag high-risk submissions *before* they're sent, so staff can fix documentation
   gaps proactively rather than appeal after the fact (see `model/` and `analyses/03` for the launch-measurement
   framework to validate impact once shipped).
3. Treat payer-specific approval rates as an ongoing dashboard metric, not a one-time finding — see
   `metrics/metrics.yml:auth_approval_rate`.

*Charts: `funnel_overall.png`, `funnel_by_payer.png`. Data: `funnel_overall.csv`, `approval_rate_by_payer.csv`.*
"""
    (HERE / "memo.md").write_text(memo, encoding="utf-8")
    print(f"\nWrote memo.md and charts to {HERE}")


if __name__ == "__main__":
    main()
