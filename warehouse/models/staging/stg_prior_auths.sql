with source as (
    select * from {{ source('raw', 'prior_auths') }}
)
select
    patient_id,
    clinic_id,
    payer,
    cpt_code,
    icd10_code,
    cast(auth_submit_date as date) as auth_submit_date,
    cast(auth_decision_date as date) as auth_decision_date,
    date_diff('day', auth_submit_date, auth_decision_date) as decision_days,
    approved,
    denial_reason_code,
    (not approved and denial_reason_code is null) as is_denial_reason_missing
from source
