# MSK Pulse — Metrics Dictionary

> Generated from `metrics/metrics.yml`. Do not hand-edit this file — edit the YAML and re-run `render_dictionary.py`.

Every number in this repo's dashboards, analyses, and memos traces back to one of these definitions. If a chart and this page disagree, the chart is wrong.

## `intake_rate`

**Owner:** data_science  
**Grain:** clinic x month

Share of referred patients who complete intake (i.e. show up and are registered as a patient) within the observation window.

**Canonical SQL**
```sql
avg(case when did_intake then 1.0 else 0.0 end)
-- from marts.patient_journey, grouped by clinic_id, referral_month
```

**Known edge cases**
- Referrals in the last 10 days of the data window are systematically under-counted for intake (right-censoring) -- exclude the most recent 2 weeks from trend charts.
- Does not distinguish "declined care" from "administrative no-show"; both count as a non-intake.

---

## `auth_approval_rate`

**Owner:** data_science  
**Grain:** payer x month (also cut by clinic, CPT)

Share of *submitted* prior-authorization requests that are approved. Denominator is submitted auths, not all referrals.

**Canonical SQL**
```sql
avg(case when approved then 1.0 else 0.0 end)
-- from marts.auth_facts where auth_submit_date is not null, grouped by payer, auth_month
```

**Known edge cases**
- Pending/in-review auths at the time of a snapshot should be excluded from the denominator, not counted as denials.
- See dq_denial_reason_monitor for a known data-quality issue with denial_reason_code on one payer feed (does not affect this rate, only the reason breakdown).

---

## `retention_90d_rate`

**Owner:** data_science  
**Grain:** cohort (referral month) x clinic

Of patients who had a first visit, the share still clinically active (a visit) at least 90 days after their first visit.

**Canonical SQL**
```sql
avg(case when did_first_visit then
      case when active_at_90_days then 1.0 else 0.0 end end)
-- from marts.patient_journey
```

**Known edge cases**
- Undefined (NULL) for patients with no first visit -- always filter to did_first_visit = true before averaging, or the rate is diluted.
- Cohorts referred in the last 90 days of the data window cannot be scored yet; exclude them rather than showing a misleadingly low rate.

---

## `engagement_score`

**Owner:** data_science  
**Grain:** patient x as-of-date

A 0-1 recency/frequency score blending visit attendance and message responsiveness in the trailing 60 days. Used as a leading indicator of churn risk, not a metric reported externally.

**Canonical SQL**
```sql
-- see analyses/02_cohorts_retention/engagement_score.py for the full
-- weighted implementation (0.6 * visit_recency_component +
-- 0.4 * message_response_component)
```

**Known edge cases**
- Patients with zero trailing-60-day events score 0, which conflates "churned" with "not yet due for a visit" -- always cross-check against expected visit cadence for the condition.

---

## `visit_conversion_rate`

**Owner:** data_science  
**Grain:** clinic x month

Of patients whose prior auth was approved, the share who attend at least one visit.

**Canonical SQL**
```sql
avg(case when auth_approved then
      case when did_first_visit then 1.0 else 0.0 end end)
-- from marts.patient_journey
```

**Known edge cases**
- Approved-but-not-yet-visited patients in the trailing 2 weeks should be excluded (visit scheduling lag), same right-censoring caveat as intake_rate.

---

## `denial_reason_missing_rate`

**Owner:** data_science (data quality)  
**Grain:** payer x month

Data-quality monitor, not a business metric: the share of denied auths missing a denial_reason_code. Should sit near a low stable baseline; a jump toward 100% for one payer indicates an upstream feed break (see analyses/04_anomaly_postmortem).

**Canonical SQL**
```sql
avg(case when denial_reason_code is null then 1.0 else 0.0 end)
-- from marts.dq_denial_reason_monitor, filtered to approved = false
```

**Known edge cases**
- A real (non-bug) source of missing reason codes is auto-denials from certain automated payer rules -- baseline is ~3-5%, not exactly 0.

---
