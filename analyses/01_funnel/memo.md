# Memo: Where MSK Pulse patients drop off

**To:** Product & Ops leadership
**From:** Data Science
**Re:** Patient journey funnel analysis

## Headline

Of 44,212 referred patients, 25,650 (58.0%) reach a first visit.
The single largest drop-off is **auth approved**, losing 10,032 patients
(27.7% of everyone who reached the prior stage).

## The funnel

| Stage | Patients | % of referred | % of prior stage |
|---|---:|---:|---:|
| referred | 44,212 | 100.0% | 100.0% |
| intake | 36,260 | 82.0% | 82.0% |
| auth submitted | 36,260 | 82.0% | 100.0% |
| auth approved | 26,228 | 59.3% | 72.3% |
| first visit | 25,650 | 58.0% | 97.8% |

## Why prior auth is the stage to fix

Auth approval is the only stage in this funnel that is (a) large, (b) not a patient-behavior problem, and
(c) directly addressable with better documentation and predictive triage. Intake drop-off is largely patient
choice / scheduling; auth denial is an operational and payer-driven leak Flagler can act on directly.

Approval rate varies sharply by payer — from 56.0% to 81.9%
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
