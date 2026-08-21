with source as (
    select * from {{ source('raw', 'clinics') }}
)
select
    clinic_id,
    clinic_name,
    ops_quality,
    reminders_cohort
from source
