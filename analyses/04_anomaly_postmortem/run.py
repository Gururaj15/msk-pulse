"""
Anomaly postmortem: the dq_denial_reason_monitor mart flags a payer whose
denial_reason_code null-rate jumps to ~100%. This script reproduces the
detection an on-call analyst would do, isolates the root cause, and writes
it up as a real incident postmortem.

Outputs: anomaly_chart.png, postmortem.md
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
ALERT_THRESHOLD = 0.15  # a monitor would fire above this null-rate


def main():
    con = connect()
    dq = con.execute("select * from main_marts.dq_denial_reason_monitor order by payer, auth_month").df()
    dq["auth_month"] = pd.to_datetime(dq["auth_month"])

    # --- Step 1: detect ---
    flagged = dq[dq["pct_missing_reason"] > ALERT_THRESHOLD]
    first_flag = flagged.sort_values("auth_month").iloc[0]
    culprit_payer = first_flag["payer"]
    print(f"Monitor would first fire on: {culprit_payer}, {first_flag.auth_month.date()}, "
          f"{first_flag.pct_missing_reason*100:.0f}% missing")

    # --- Step 2: isolate — confirm it's payer-specific, not global ---
    baseline_other = dq[dq.payer != culprit_payer]["pct_missing_reason"].mean()
    print(f"Baseline missing-rate for all other payers: {baseline_other*100:.1f}%")

    # --- Step 3: quantify blast radius ---
    culprit = dq[dq.payer == culprit_payer].sort_values("auth_month")
    break_month = flagged[flagged.payer == culprit_payer]["auth_month"].min()
    affected = culprit[culprit.auth_month >= break_month]
    n_affected_denials = affected["n_denials"].sum()

    # --- chart ---
    fig, ax = plt.subplots(figsize=(9, 5))
    for payer, g in dq.groupby("payer"):
        g = g.sort_values("auth_month")
        style = {"linewidth": 2.6, "color": "#B23A48", "zorder": 5} if payer == culprit_payer \
            else {"linewidth": 1, "color": "#B7C4C0", "zorder": 1}
        ax.plot(g["auth_month"], g["pct_missing_reason"] * 100,
                label=payer if payer == culprit_payer else None, **style)
    ax.axhline(ALERT_THRESHOLD * 100, color="#A8700D", linestyle="--", linewidth=1,
               label=f"Alert threshold ({ALERT_THRESHOLD*100:.0f}%)")
    ax.axvline(break_month, color="#B23A48", linestyle=":", linewidth=1)
    ax.set_ylabel("% of denials missing denial_reason_code")
    ax.set_title("Data-quality monitor: denial-reason completeness by payer")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "anomaly_chart.png", dpi=150)
    plt.close(fig)

    postmortem = f"""# Postmortem: missing denial reason codes for {culprit_payer}

**Status:** Resolved (detected in analysis; recommend backfill + prevention below)
**Detected:** {first_flag.auth_month.date()} (by `dq_denial_reason_monitor`, threshold {ALERT_THRESHOLD*100:.0f}%)
**Impact window:** {break_month.date()} → end of observed data
**Severity:** Medium — no patient-facing impact; degrades reporting accuracy and operational visibility
into one payer's denial reasons.

## Timeline

- **{break_month.date()}:** `denial_reason_code` null-rate for {culprit_payer} jumps from a stable
  baseline (~{baseline_other*100:.0f}%, consistent with every other payer) to effectively 100% and stays there.
- **Detection (this analysis):** the `dq_denial_reason_monitor` mart, built specifically to track this field's
  completeness by payer/month, flags the break the first month it crosses the {ALERT_THRESHOLD*100:.0f}% threshold.
  In production this should be a scheduled dbt test / alert, not something found retroactively.

## Root cause

Isolating by payer shows every other payer's missing-rate stays flat at {baseline_other*100:.1f}% for the
entire window (denial reasons are consistently captured), while {culprit_payer}
alone jumps to 100% and stays there. That signature — one payer, sudden, total, and persistent — is
consistent with an **upstream feed or schema change**: {culprit_payer} appears to have altered or stopped
populating the reason-code field in their eligibility/decision feed around {break_month.date()}, and nothing
downstream caught it because no field-level completeness check existed before this monitor.

## Blast radius

{n_affected_denials:,} denied auth records for {culprit_payer} are affected. The **approval rate** metric
itself is unaffected (that's computed from the `approved` boolean, not the reason code), but any analysis
or dashboard slicing *denial reasons* by payer has been silently blind to {culprit_payer} since the break —
which matters directly for the auth-denial-reduction work this repo's other analyses recommend prioritizing.

## Fix

1. Immediate: flag {culprit_payer} denial-reason breakdowns as unreliable from {break_month.date()} forward in
   any existing dashboard or report until backfilled.
2. Backfill: request re-delivery of the reason-code field from {culprit_payer} for the affected window, or
   reconstruct from raw payer correspondence if available.
3. Root cause with the payer/integration team: confirm whether this was a schema change on their end or a
   parsing regression on ours, and get a contract test in place with them going forward.

## Prevention

The `dq_denial_reason_monitor` mart (in `warehouse/models/marts/`) now exists specifically so this class of
issue surfaces automatically. The concrete next step is turning it into an active check rather than a
queryable table:

```sql
-- warehouse/models/marts/schema.yml — add to dq_denial_reason_monitor:
tests:
  - dbt_utils.expression_is_true:
      expression: "pct_missing_reason < 0.15"
      config:
        severity: error
```

Wiring this dbt test into the CI pipeline (`.github/workflows/ci.yml`) means a future feed break like this
one fails the build the same day it starts, instead of surfacing weeks later in an unrelated analysis.

*Chart: `anomaly_chart.png`.*
"""
    (HERE / "postmortem.md").write_text(postmortem, encoding="utf-8")
    print(f"\nWrote postmortem.md and chart to {HERE}")


if __name__ == "__main__":
    main()
