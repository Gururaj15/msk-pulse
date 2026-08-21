# Memo: Why is Coastal Spine & Sport underperforming on intake?

**To:** Clinic Operations
**From:** Data Science
**Re:** Ad hoc investigation — Clinic_07 intake rate

## Question as asked

"Coastal Spine & Sport looks like it's losing more referred patients than other clinics — is that real, and if so why?"

## Finding

Yes, it's real and it's the clearest outlier in the network: Clinic_07's intake rate is
**50.9%**, versus a **85.1%** average across the other 11
clinics — a gap of 34 points, roughly 40%
worse than peers.

## What it isn't

- **Not a referral-quality issue.** Breaking intake rate down by referral source, Clinic_07 underperforms
  peers by a similar -34-point margin *within every source* (PCP referrals, self-pay ads, etc.) —
  so this isn't a matter of getting lower-intent referrals, it's something happening after the referral arrives.
- **Not a recent blip.** The monthly trend (`clinic_comparison.png`, right panel) shows Clinic_07 tracking
  below peers in most months across the full window, not a one-time dip — this is a
  standing operational issue, not a recent event worth waiting out.
- **Also slower, not just lower.** Among referrals that do complete intake, Clinic_07 takes
  5.0 average days from referral to intake, versus 5.0
  days for peers — the clinic isn't just converting fewer referrals, it's converting the ones it does more slowly too,
  which points toward a capacity/throughput issue rather than a one-off filtering problem.

## What it likely is

Combined with the pattern above, the leading hypothesis is a **front-desk / scheduling capacity or process
issue** at this clinic specifically — referrals are arriving at a normal rate and normal quality, but a
meaningfully larger share never convert to a scheduled, registered patient. That is consistent with problems
like understaffed intake coordination, a broken or slow callback process, or an EMR/scheduling integration
issue unique to this site — not a clinical or demand-side problem.

## Recommendation

1. Ops to pull Clinic_07's front-desk staffing levels and average callback time for the same window —
   this analysis narrows the cause to "something in the referral-to-intake handoff," not exactly which part.
2. If callback time is the driver, a fast test: track `days_referral_to_intake` (already in
   `patient_journey`) weekly for this clinic after any process fix, rather than waiting a full quarter to
   re-measure the intake rate.
3. Worth flagging as a template: this three-step method (compare to peers → rule out referral mix → check
   persistence over time) is reusable any time a clinic-level metric looks off.

*Chart: `clinic_comparison.png`.*
