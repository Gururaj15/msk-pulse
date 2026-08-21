# Memo: Did the appointment-reminders feature work?

**To:** Product & Engineering
**From:** Data Science
**Re:** Post-launch measurement of the reminders feature (launched 2025-12-01, half of clinics)

## Headline

Yes — reminders increased visit attendance by an estimated **+6.0 percentage points**
(95% CI: +5.1 to +6.9pp), after correcting for a secular attendance trend that
was moving in both treatment and control clinics regardless of the feature.

## Why the naive number is wrong

Looking only at treatment clinics before vs. after gives **+7.5pp** — inflated, because it
also captures whatever was happening industry- or season-wide in that window. Control clinics moved
**+1.5pp** over the same period with no reminders feature at all. The diff-in-diff estimate
nets that trend out.

## Estimates by method

| Method | Estimate | Note |
|---|---:|---|
| Naive before/after | +7.5pp | Confounded by secular trend — don't use for decisions |
| Diff-in-diff | +6.0pp | 95% CI [+5.1, +6.9]pp, clinic-level bootstrap — **primary estimate** |
| CUPED-adjusted | +5.8pp | variance reduced 10% vs. raw post-period comparison |

**A note on CUPED here:** with only 12 clinics total (6 per arm), the pre/post
covariance used to fit CUPED's adjustment coefficient is itself noisy, and in this run CUPED *increased*
variance rather than reducing it — the technique needs enough independent units to estimate that
covariance reliably, and clinic-level randomization doesn't give us that here. This is exactly the kind of
thing to check before trusting a CUPED number: at patient-level randomization with thousands of units it
would be the better estimator; at clinic-level randomization with a handful of clinics, diff-in-diff alone
is more trustworthy. The diff-in-diff estimate above is what this memo's recommendation relies on.

## Recommendation

1. Ship reminders to all remaining clinics — the diff-in-diff effect is positive and the confidence interval excludes zero.
2. This is the template for every future feature launch: define the metric and randomization unit *before*
   launch, hold out a control group, and report diff-in-diff as the primary estimate — never a naive before/after.
   Reach for CUPED only when the randomization unit has enough independent replicates to estimate its
   adjustment reliably (patient-level, not a handful of clinics).
3. Proposed instrumentation for the next launch: log `reminder_sent`, `reminder_channel`, and
   `reminder_to_visit_hours` as first-class events so we can also measure dose-response, not just presence/absence.

*Chart: `naive_vs_did.png`. Data: `results.csv`.*
