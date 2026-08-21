-- Singular data-quality test: fails (returns rows) if any payer/month has a
-- denial_reason_code null-rate above the alert threshold. This is exactly
-- the check that would have caught the BCBS PPO feed break in
-- analyses/04_anomaly_postmortem the same month it started, instead of
-- weeks later in an unrelated analysis.
--
-- Configured as severity: warn at the model level in schema.yml because this
-- portfolio's synthetic history has an intentionally-planted, already-past
-- break -- in a real warehouse with clean history this should be severity: error.

{{ config(severity = 'warn') }}

select *
from {{ ref('dq_denial_reason_monitor') }}
where pct_missing_reason > 0.15
