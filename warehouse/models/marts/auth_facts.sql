-- One row per prior-auth request: the training/analysis table for both the
-- denial-risk model and the payer/CPT approval-rate cuts.
select
    a.patient_id,
    a.clinic_id,
    c.clinic_name,
    c.ops_quality,
    p.age,
    p.sex,
    p.condition,
    a.icd10_code,
    a.cpt_code,
    a.payer,
    a.auth_submit_date,
    date_trunc('month', a.auth_submit_date) as auth_month,
    a.auth_decision_date,
    a.decision_days,
    a.approved,
    a.denial_reason_code,
    a.is_denial_reason_missing
from {{ ref('stg_prior_auths') }} a
left join {{ ref('stg_clinics') }} c on a.clinic_id = c.clinic_id
left join {{ ref('stg_patients') }} p on a.patient_id = p.patient_id
