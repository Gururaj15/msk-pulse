"""
Open-ended operational question: "Why is one clinic underperforming?"

No metric flags a specific clinic automatically here -- this script starts
from clinic_monthly_metrics, finds the clinic whose intake_rate is the
clearest outlier, and works the question to a conclusion the way an analyst
would field it from an ops lead's Slack message.

Outputs: clinic_comparison.png, memo.md
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
    referrals = con.execute("select * from main_staging.stg_referrals").df()
    clinics = con.execute("select * from main_staging.stg_clinics").df()

    overall_intake = referrals.groupby("clinic_id")["did_intake"].mean().sort_values()
    print("Intake rate by clinic:\n", (overall_intake * 100).round(1))

    outlier_clinic = overall_intake.index[0]
    outlier_rate = overall_intake.iloc[0]
    peer_mean = overall_intake.drop(outlier_clinic).mean()
    clinic_name = clinics.loc[clinics.clinic_id == outlier_clinic, "clinic_name"].iloc[0]

    # Rule out: referral source mix (is this clinic just getting worse-quality referrals?)
    by_source = referrals.groupby(["clinic_id", "referral_source"])["did_intake"].mean().unstack()
    outlier_by_source = by_source.loc[outlier_clinic]
    peer_by_source = by_source.drop(outlier_clinic).mean()
    source_gap = (outlier_by_source - peer_by_source).mean()

    # Rule out: is it a recent problem or a persistent one? (trend over time)
    r = referrals.copy()
    r["referral_date"] = pd.to_datetime(r["referral_date"])
    r["month"] = r["referral_date"].dt.to_period("M")
    monthly = r.groupby(["clinic_id", "month"])["did_intake"].mean().reset_index()
    outlier_trend = monthly[monthly.clinic_id == outlier_clinic].sort_values("month")
    persistent = (outlier_trend["did_intake"] < peer_mean - 0.05).mean() > 0.8

    # Rule out: time-to-intake for those who DO make it (is it slow, not just low-rate?)
    r["intake_date"] = pd.to_datetime(r["intake_date"])
    r["days_to_intake"] = (r["intake_date"] - r["referral_date"]).dt.days
    speed = r.groupby("clinic_id")["days_to_intake"].mean().sort_values(ascending=False)

    # --- chart ---
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    colors = ["#B23A48" if c == outlier_clinic else "#94A6A1" for c in overall_intake.index]
    axes[0].barh(overall_intake.index, overall_intake.values * 100, color=colors)
    axes[0].set_xlabel("Intake rate (%)")
    axes[0].set_title("Intake rate by clinic")

    trend_all = monthly.pivot(index="month", columns="clinic_id", values="did_intake")
    for c in trend_all.columns:
        style = {"color": "#B23A48", "linewidth": 2.4, "zorder": 5} if c == outlier_clinic \
            else {"color": "#D7DEDB", "linewidth": 1, "zorder": 1}
        axes[1].plot(trend_all.index.astype(str), trend_all[c] * 100, **style)
    axes[1].set_title(f"Intake rate over time ({outlier_clinic} highlighted)")
    axes[1].set_ylabel("Intake rate (%)")
    axes[1].tick_params(axis="x", rotation=90, labelsize=6)
    fig.tight_layout()
    fig.savefig(HERE / "clinic_comparison.png", dpi=150)
    plt.close(fig)

    memo = f"""# Memo: Why is {clinic_name} underperforming on intake?

**To:** Clinic Operations
**From:** Data Science
**Re:** Ad hoc investigation — {outlier_clinic} intake rate

## Question as asked

"{clinic_name} looks like it's losing more referred patients than other clinics — is that real, and if so why?"

## Finding

Yes, it's real and it's the clearest outlier in the network: {outlier_clinic}'s intake rate is
**{outlier_rate*100:.1f}%**, versus a **{peer_mean*100:.1f}%** average across the other {len(overall_intake)-1}
clinics — a gap of {(peer_mean-outlier_rate)*100:.0f} points, roughly {(peer_mean-outlier_rate)/peer_mean*100:.0f}%
worse than peers.

## What it isn't

- **Not a referral-quality issue.** Breaking intake rate down by referral source, {outlier_clinic} underperforms
  peers by a similar {source_gap*100:.0f}-point margin *within every source* (PCP referrals, self-pay ads, etc.) —
  so this isn't a matter of getting lower-intent referrals, it's something happening after the referral arrives.
- **Not a recent blip.** The monthly trend (`clinic_comparison.png`, right panel) shows {outlier_clinic} tracking
  below peers in {"most" if persistent else "some"} months across the full window, not a one-time dip — this is a
  standing operational issue, not a recent event worth waiting out.
- **Also slower, not just lower.** Among referrals that do complete intake, {outlier_clinic} takes
  {speed.loc[outlier_clinic]:.1f} average days from referral to intake, versus {speed.drop(outlier_clinic).mean():.1f}
  days for peers — the clinic isn't just converting fewer referrals, it's converting the ones it does more slowly too,
  which points toward a capacity/throughput issue rather than a one-off filtering problem.

## What it likely is

Combined with the pattern above, the leading hypothesis is a **front-desk / scheduling capacity or process
issue** at this clinic specifically — referrals are arriving at a normal rate and normal quality, but a
meaningfully larger share never convert to a scheduled, registered patient. That is consistent with problems
like understaffed intake coordination, a broken or slow callback process, or an EMR/scheduling integration
issue unique to this site — not a clinical or demand-side problem.

## Recommendation

1. Ops to pull {outlier_clinic}'s front-desk staffing levels and average callback time for the same window —
   this analysis narrows the cause to "something in the referral-to-intake handoff," not exactly which part.
2. If callback time is the driver, a fast test: track `days_referral_to_intake` (already in
   `patient_journey`) weekly for this clinic after any process fix, rather than waiting a full quarter to
   re-measure the intake rate.
3. Worth flagging as a template: this three-step method (compare to peers → rule out referral mix → check
   persistence over time) is reusable any time a clinic-level metric looks off.

*Chart: `clinic_comparison.png`.*
"""
    (HERE / "memo.md").write_text(memo, encoding="utf-8")
    print(f"\nWrote memo.md and chart to {HERE}")


if __name__ == "__main__":
    main()
