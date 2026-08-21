-- Clinic x month rollup of the core operational metrics. Backs the exec
-- dashboard and the clinic deep-dive analysis.
with j as (
    select * from {{ ref('patient_journey') }}
)
select
    clinic_id,
    clinic_name,
    referral_month,
    count(*) as n_referrals,
    avg(case when did_intake then 1.0 else 0.0 end) as intake_rate,
    avg(case when did_submit_auth then 1.0 else 0.0 end) as auth_submit_rate,
    avg(case when did_submit_auth and auth_approved then 1.0
             when did_submit_auth then 0.0 end) as auth_approval_rate,
    avg(case when auth_approved then case when did_first_visit then 1.0 else 0.0 end end) as visit_conversion_rate,
    avg(case when did_first_visit then case when active_at_90_days then 1.0 else 0.0 end end) as retention_90d_rate,
    avg(auth_decision_days) as avg_decision_days
from j
group by 1, 2, 3
