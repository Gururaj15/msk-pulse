with source as (
    select * from {{ source('raw', 'visits') }}
)
select
    patient_id,
    clinic_id,
    visit_number,
    cast(visit_date as date) as visit_date,
    attended
from source
