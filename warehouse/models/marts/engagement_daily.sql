-- Daily per-patient engagement events (visits + messages), unioned, for
-- building recency/frequency engagement scores and retention curves.
with visit_events as (
    select patient_id, clinic_id, visit_date as event_date, 'visit' as event_type,
        attended as positive_event
    from {{ ref('stg_visits') }}
),
message_events as (
    select patient_id, clinic_id, message_date as event_date, 'message' as event_type,
        patient_replied as positive_event
    from {{ ref('stg_messages') }}
)
select * from visit_events
union all
select * from message_events
