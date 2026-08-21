# Memo: Retention isn't one number — it depends heavily on payer and condition

**To:** Product & Ops leadership
**From:** Data Science
**Re:** Cohort retention & survival analysis

## Headline

Median time-to-churn ranges from **26 days** (Medicaid (State)) to
**36+ days** (Medicare Part B) depending on payer. A single blended
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
| Medicaid (State) | 2,720 | 26 |
| BCBS PPO | 3,949 | 34 |
| UnitedHealthcare | 4,765 | 35 |
| Aetna Commercial | 4,913 | 36 |
| Cigna | 3,060 | 36 |
| Medicare Part B | 6,566 | 36 |

## Recommendation

1. Report retention by payer and condition on the exec dashboard, not just blended — the blended number masks
   a >2x spread in median active duration.
2. Use `engagement_score.csv` (recency-weighted visit + message-response signal) as a leading indicator to
   flag at-risk patients before they fully churn, not after.
3. Feed the low-retention segments into the feature-launch prioritization in `analyses/03` — the reminders
   feature should be evaluated for differential effect by payer/condition, not just overall.

*Charts: `retention_triangle.png`, `survival_by_payer.png`, `survival_by_condition.png`.*
