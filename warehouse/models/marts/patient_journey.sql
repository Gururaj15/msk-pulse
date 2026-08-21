-- One row per patient: the full referral -> intake -> auth -> first-visit ->
-- active-at-90-days funnel, plus the attributes analyses slice by.
with patients as (
    select * from {{ ref('stg_patients') }}
),
referrals as (
    select * from {{ ref('stg_referrals') }}
),
auths as (
    -- a patient can in theory have >1 auth; take the first submitted one
    -- as the auth tied to this referral/episode
    select *,
        row_number() over (partition by patient_id order by auth_submit_date) as auth_rn
    from {{ ref('stg_prior_auths') }}
),
first_auth as (
    select * from auths where auth_rn = 1
),
visits as (
    select
        patient_id,
        min(case when attended then visit_date end) as first_visit_date,
        count(case when attended then 1 end) as visits_attended,
        max(case when attended then visit_date end) as last_visit_date
    from {{ ref('stg_visits') }}
    group by 1
),
joined as (
    select
        p.patient_id,
        p.clinic_id,
        c.clinic_name,
        c.reminders_cohort,
        p.age,
        p.sex,
        p.condition,
        p.icd10_code,
        p.payer,
        p.referral_source,
        p.referral_date,

        r.did_intake,
        r.intake_date,
        r.days_referral_to_intake,

        (fa.patient_id is not null) as did_submit_auth,
        fa.auth_submit_date,
        fa.approved as auth_approved,
        fa.denial_reason_code,
        fa.decision_days as auth_decision_days,

        (v.first_visit_date is not null) as did_first_visit,
        v.first_visit_date,
        v.visits_attended,
        v.last_visit_date,
        date_diff('day', v.first_visit_date, v.last_visit_date) as days_active_span,
        (v.last_visit_date >= v.first_visit_date + interval 90 day) as active_at_90_days

    from patients p
    left join {{ ref('stg_clinics') }} c on p.clinic_id = c.clinic_id
    left join referrals r on p.patient_id = r.patient_id
    left join first_auth fa on p.patient_id = fa.patient_id
    left join visits v on p.patient_id = v.patient_id
)
select
    *,
    date_trunc('month', referral_date) as referral_month,
    case
        when not did_intake then 'dropped_before_intake'
        when not did_submit_auth then 'dropped_before_auth'
        when did_submit_auth and not auth_approved then 'dropped_auth_denied'
        when auth_approved and not did_first_visit then 'dropped_after_approval'
        when did_first_visit then 'reached_first_visit'
        else 'unknown'
    end as funnel_stage_reached
from joined
