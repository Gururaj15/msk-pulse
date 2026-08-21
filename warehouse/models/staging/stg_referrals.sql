with source as (
    select * from {{ source('raw', 'referrals') }}
)
select
    patient_id,
    clinic_id,
    cast(referral_date as date) as referral_date,
    referral_source,
    did_intake,
    cast(intake_date as date) as intake_date,
    date_diff('day', referral_date, intake_date) as days_referral_to_intake
from source
