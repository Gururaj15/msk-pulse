with source as (
    select * from {{ source('raw', 'messages') }}
)
select
    patient_id,
    clinic_id,
    cast(message_date as date) as message_date,
    channel,
    patient_replied
from source
