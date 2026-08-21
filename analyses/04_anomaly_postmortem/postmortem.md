# Postmortem: missing denial reason codes for BCBS PPO

**Status:** Resolved (detected in analysis; recommend backfill + prevention below)
**Detected:** 2025-08-01 (by `dq_denial_reason_monitor`, threshold 15%)
**Impact window:** 2025-08-01 → end of observed data
**Severity:** Medium — no patient-facing impact; degrades reporting accuracy and operational visibility
into one payer's denial reasons.

## Timeline

- **2025-08-01:** `denial_reason_code` null-rate for BCBS PPO jumps from a stable
  baseline (~0%, consistent with every other payer) to effectively 100% and stays there.
- **Detection (this analysis):** the `dq_denial_reason_monitor` mart, built specifically to track this field's
  completeness by payer/month, flags the break the first month it crosses the 15% threshold.
  In production this should be a scheduled dbt test / alert, not something found retroactively.

## Root cause

Isolating by payer shows every other payer's missing-rate stays flat at 0.0% for the
entire window (denial reasons are consistently captured), while BCBS PPO
alone jumps to 100% and stays there. That signature — one payer, sudden, total, and persistent — is
consistent with an **upstream feed or schema change**: BCBS PPO appears to have altered or stopped
populating the reason-code field in their eligibility/decision feed around 2025-08-01, and nothing
downstream caught it because no field-level completeness check existed before this monitor.

## Blast radius

640 denied auth records for BCBS PPO are affected. The **approval rate** metric
itself is unaffected (that's computed from the `approved` boolean, not the reason code), but any analysis
or dashboard slicing *denial reasons* by payer has been silently blind to BCBS PPO since the break —
which matters directly for the auth-denial-reduction work this repo's other analyses recommend prioritizing.

## Fix

1. Immediate: flag BCBS PPO denial-reason breakdowns as unreliable from 2025-08-01 forward in
   any existing dashboard or report until backfilled.
2. Backfill: request re-delivery of the reason-code field from BCBS PPO for the affected window, or
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
