-- Data-quality monitor: tracks the monthly null-rate of denial_reason_code
-- among denied auths, by payer. A sudden jump to ~100% for one payer is the
-- signature of an upstream feed break (see analyses/04_anomaly_postmortem).
select
    payer,
    auth_month,
    count(*) as n_denials,
    avg(case when denial_reason_code is null then 1.0 else 0.0 end) as pct_missing_reason
from {{ ref('auth_facts') }}
where approved = false
group by 1, 2
