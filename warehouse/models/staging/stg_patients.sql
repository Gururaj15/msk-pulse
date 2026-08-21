with source as (
    select * from {{ source('raw', 'patients') }}
)
select
    patient_id,
    clinic_id,
    age,
    sex,
    condition,
    icd10_code,
    payer,
    referral_source,
    cast(referral_date as date) as referral_date
from source
