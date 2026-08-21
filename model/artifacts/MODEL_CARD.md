# Model Card — Prior-Auth Denial-Risk Model (v1)

## Intended use

Flags a prior-authorization request as **high denial-risk** *before submission* so staff can review and
fix documentation gaps proactively, rather than appealing after a denial. This is a **decision-support**
tool for clinic ops staff, not an automated approval/denial system — every flagged submission still goes
through normal human review.

## Training data

Synthetic MSK clinic network data (see `data_generator/`), 26,525 training
records. **Not real patient or payer data.** Approval-rate base rates are loosely calibrated to public
CMS Part B statistics but this model is a portfolio demonstration, not a validated clinical or claims tool.

## Features

Only fields known at *submission* time are used — payer, condition, ICD-10, CPT code, clinic, patient
age/sex, and submission seasonality. `decision_days`, `auth_decision_date`, and `denial_reason_code`
are deliberately excluded: they are only known *after* a decision and would leak the outcome.

## Performance (time-based test split — the most recent 5,684 submissions,
model never trained on data from after the training window)

| Metric | Value |
|---|---:|
| ROC-AUC (approval) | 0.679 |
| ROC-AUC, calibrated | 0.675 |
| PR-AUC (denial class) | 0.429 |
| Denial recall @ threshold 0.22 | 81.6% |
| Denial precision @ threshold 0.22 | 36.3% |

The operating threshold is tuned for **80% denial recall** — catching most true
denials before submission is worth more operationally than avoiding false alarms, since a flagged-but-
actually-fine submission just gets a quick extra review, while a missed denial costs a full appeal cycle.

## Calibration

Probabilities are isotonic-calibrated on a held-out split (`calibration_curve.png`) — a predicted 70%
approval probability should reflect roughly 70% observed approval in that probability band, which matters
for staff trusting the score enough to act on it, not just rank-order it.

## Top denial-risk drivers (mean |SHAP|)

1. `cpt_code_97110`
2. `cpt_code_97140`
3. `payer_Medicaid (State)`
4. `payer_UnitedHealthcare`
5. `payer_Medicare Part B`
6. `ops_quality`
7. `cpt_code_97116`
8. `age`
9. `payer_BCBS PPO`
10. `submit_month_cos`

See `shap_summary.png` for the full distribution of each feature's effect.

## Limitations

- Trained on synthetic data with a generator-defined causal structure — real payer/clinical denial patterns
  will differ, and this model would need retraining on real (de-identified) data before any production use.
- No fairness audit performed. Any real deployment must check for disparate impact across protected classes
  before flagging patients differently by demographic-correlated features (e.g., payer often correlates with
  socioeconomic factors).
- Time-based split guards against look-ahead leakage but does not guarantee performance holds under future
  payer policy changes — recommend a scheduled retrain + drift monitor, not a train-once deployment.

*Trained 2026-08-21T02:51:52.500465+00:00. Artifacts: `pipeline.joblib`, `calibrator.joblib`, `metadata.json`.*
