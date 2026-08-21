"""
MSK Pulse synthetic data generator.

Simulates a multi-clinic MSK (musculoskeletal) provider network over 24 months:
patients, referrals, intake, prior-authorization requests, visits, PT adherence,
engagement messaging, and churn.

The generator has real causal structure (payer -> approval odds, condition ->
visit cadence, engagement -> retention) and plants three storylines that the
analytics modules later "discover":

  1. A payer-feed schema change in month 14 that silently nulls the
     `denial_reason_code` field for one payer (data-quality anomaly).
  2. An appointment-reminders feature launched in month 18, rolled out to a
     random half of clinics (a feature to measure with diff-in-diff).
  3. One clinic (Clinic 07) with a broken intake process causing elevated
     drop-off between referral and intake (an operational deep-dive).

All data is synthetic. Base rates are loosely calibrated to publicly reported
MSK utilization and prior-authorization approval statistics, but no real
patient, clinic, or payer data is used anywhere in this generator.

Usage:
    python generate.py --out ../data/raw --seed 42
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

START_DATE = date(2024, 7, 1)
N_MONTHS = 24
N_CLINICS = 12
N_PATIENTS_TARGET = 40_000

CLINIC_NAMES = [
    "Ridgeline Ortho & Spine", "Harbor Point MSK", "Cascade Sports Medicine",
    "Bluestem Physical Medicine", "Foothill Rehab Partners", "Summit Joint Clinic",
    "Coastal Spine & Sport", "Ironwood MSK Group", "Prairie Motion Clinic",
    "Redstone Ortho Associates", "Willowbrook Rehab Center", "Northgate MSK Institute",
]
CLINIC_INTAKE_BROKEN = "Clinic_07"  # Ironwood MSK Group — broken intake storyline

PAYERS = {
    # engagement_bias reflects real-world correlates of retention such as
    # transportation access and plan-driven copay burden -- NOT an assumption
    # that the payer itself causes churn.
    "Aetna Commercial":     {"share": 0.18, "base_approval": 0.82, "engagement_bias": 0.03},
    "UnitedHealthcare":     {"share": 0.20, "base_approval": 0.78, "engagement_bias": 0.02},
    "Cigna":                {"share": 0.12, "base_approval": 0.80, "engagement_bias": 0.02},
    "Medicare Part B":      {"share": 0.22, "base_approval": 0.88, "engagement_bias": 0.05},
    "Medicaid (State)":     {"share": 0.14, "base_approval": 0.68, "engagement_bias": -0.08},
    "BCBS PPO":             {"share": 0.14, "base_approval": 0.83, "engagement_bias": 0.01},
}
ANOMALY_PAYER = "BCBS PPO"          # payer whose feed breaks in month 14
ANOMALY_MONTH_INDEX = 13            # 0-indexed -> month 14 of 24
FEATURE_LAUNCH_MONTH_INDEX = 17     # month 18 of 24 (reminders feature)

CONDITIONS = {
    # condition: (icd10, share, base_visit_cadence_days, chronicity 0-1)
    "Low back pain":        ("M54.5",  0.24, 10, 0.55),
    "Knee osteoarthritis":  ("M17.9",  0.16, 12, 0.70),
    "Rotator cuff injury":  ("M75.10", 0.13,  9, 0.45),
    "Cervical radiculopathy": ("M54.12", 0.10, 11, 0.50),
    "Post-op knee (ACL)":   ("Z47.89", 0.09,  7, 0.85),
    "Hip osteoarthritis":   ("M16.9",  0.08, 13, 0.65),
    "Plantar fasciitis":    ("M72.2",  0.08,  8, 0.30),
    "Lateral epicondylitis":("M77.10", 0.06,  9, 0.35),
    "Post-op shoulder":     ("Z47.89", 0.06,  7, 0.80),
}


# CPT-level approval modifiers: imaging tends to draw more medical-necessity
# scrutiny, routine therapy codes are close to rubber-stamped, and surgical
# codes draw the most scrutiny of all. This is the single largest source of
# individually learnable signal in the auth dataset (payer and clinic effects
# alone are too coarse-grained to separate individual outcomes well).
CPT_APPROVAL_MODIFIER = {
    "72110": -0.13, "72040": -0.13,               # spine imaging
    "73562": -0.10, "73030": -0.10, "73521": -0.10, "73620": -0.10, "73070": -0.10,  # joint imaging
    "97110": 0.10, "97140": 0.10, "97116": 0.10,   # routine PT/manual therapy
    "20610": -0.03, "20550": -0.03, "20551": -0.03,  # injections
    "29827": -0.15, "29888": -0.18, "23412": -0.18, "64483": -0.14,  # surgical / invasive
}

CPT_BY_CONDITION = {
    "Low back pain": ["72110", "97110", "97140"],
    "Knee osteoarthritis": ["73562", "97110", "20610"],
    "Rotator cuff injury": ["73030", "97110", "29827"],
    "Cervical radiculopathy": ["72040", "97140", "64483"],
    "Post-op knee (ACL)": ["29888", "97110", "97116"],
    "Hip osteoarthritis": ["73521", "20610", "97110"],
    "Plantar fasciitis": ["73620", "97110", "20550"],
    "Lateral epicondylitis": ["73070", "20551", "97140"],
    "Post-op shoulder": ["23412", "97110", "97140"],
}

REFERRAL_SOURCES = ["PCP referral", "Ortho self-pay ad", "Employer wellness",
                     "Insurance directory", "Patient word-of-mouth", "ED discharge"]

rng_global = np.random.default_rng(42)


def month_index_to_date(i: int) -> date:
    y = START_DATE.year + (START_DATE.month - 1 + i) // 12
    m = (START_DATE.month - 1 + i) % 12 + 1
    return date(y, m, 1)


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=int(days))


@dataclass
class GenConfig:
    seed: int = 42
    out_dir: Path = Path("../data/raw")


def generate(cfg: GenConfig) -> None:
    rng = np.random.default_rng(cfg.seed)
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)

    clinics = pd.DataFrame({
        "clinic_id": [f"Clinic_{i+1:02d}" for i in range(N_CLINICS)],
        "clinic_name": CLINIC_NAMES,
        # random baseline quality multiplier per clinic (intake -> auth speed etc.)
        "ops_quality": rng.normal(1.0, 0.08, N_CLINICS).clip(0.75, 1.25),
    })
    # half of clinics get the reminders feature at launch month (deterministic split for reproducibility)
    clinics = clinics.sort_values("clinic_id").reset_index(drop=True)
    clinics["reminders_cohort"] = ["treatment" if i % 2 == 0 else "control" for i in range(N_CLINICS)]

    condition_names = list(CONDITIONS.keys())
    condition_probs = np.array([v[1] for v in CONDITIONS.values()])
    condition_probs = condition_probs / condition_probs.sum()

    payer_names = list(PAYERS.keys())
    payer_probs = np.array([v["share"] for v in PAYERS.values()])
    payer_probs = payer_probs / payer_probs.sum()

    # ---- monthly referral volume with seasonality + gentle growth trend ----
    monthly_referrals = []
    base = N_PATIENTS_TARGET / N_MONTHS
    for m in range(N_MONTHS):
        month_date = month_index_to_date(m)
        seasonal = 1.0 + 0.12 * np.sin(2 * np.pi * (month_date.month - 1) / 12 + 1.0)
        # New Year / post-injury bump in Jan, summer sports dip in July
        if month_date.month == 1:
            seasonal *= 1.15
        growth = 1.0 + 0.012 * m  # slow organic growth
        vol = int(base * seasonal * growth)
        monthly_referrals.append(vol)

    patients_rows = []
    referrals_rows = []
    auths_rows = []
    visits_rows = []
    messages_rows = []
    pid_counter = 0

    for m in range(N_MONTHS):
        month_date = month_index_to_date(m)
        n_ref = monthly_referrals[m]
        clinic_ids = rng.choice(clinics["clinic_id"], size=n_ref)
        conditions = rng.choice(condition_names, size=n_ref, p=condition_probs)
        payers = rng.choice(payer_names, size=n_ref, p=payer_probs)
        sources = rng.choice(REFERRAL_SOURCES, size=n_ref)
        ages = rng.normal(52, 16, n_ref).clip(18, 92).astype(int)
        sexes = rng.choice(["F", "M"], size=n_ref, p=[0.56, 0.44])

        for i in range(n_ref):
            pid_counter += 1
            patient_id = f"P{pid_counter:07d}"
            clinic_id = clinic_ids[i]
            condition = conditions[i]
            payer = payers[i]
            icd10, _, cadence_days, chronicity = CONDITIONS[condition]
            cpt_options = CPT_BY_CONDITION[condition]
            referral_date = add_days(month_date, int(rng.integers(0, 28)))
            ops_q = clinics.loc[clinics.clinic_id == clinic_id, "ops_quality"].iloc[0]

            # --- Storyline 3: Clinic_07 has a broken intake process ---
            intake_broken_penalty = 0.35 if clinic_id == CLINIC_INTAKE_BROKEN else 0.0

            patients_rows.append({
                "patient_id": patient_id, "clinic_id": clinic_id,
                "age": ages[i], "sex": sexes[i], "condition": condition,
                "icd10_code": icd10, "payer": payer,
                "referral_source": sources[i], "referral_date": referral_date,
            })

            # --- Intake step ---
            intake_prob = 0.86 * ops_q - intake_broken_penalty
            intake_prob = np.clip(intake_prob, 0.05, 0.98)
            did_intake = rng.random() < intake_prob
            intake_date = add_days(referral_date, int(rng.integers(1, 10))) if did_intake else None

            referrals_rows.append({
                "patient_id": patient_id, "clinic_id": clinic_id,
                "referral_date": referral_date, "referral_source": sources[i],
                "did_intake": did_intake, "intake_date": intake_date,
            })

            if not did_intake:
                continue

            # --- Prior auth step ---
            payer_cfg = PAYERS[payer]
            base_approval = payer_cfg["base_approval"]
            cpt_code = rng.choice(cpt_options)
            cpt_modifier = CPT_APPROVAL_MODIFIER.get(cpt_code, 0.0)
            # stricter payers penalize chronic conditions and weak documentation more heavily
            strict_payer = payer in ("Medicaid (State)", "UnitedHealthcare")
            chronicity_penalty = (0.20 if strict_payer else 0.09) * chronicity
            # clinic documentation quality (ops_quality) matters most for CPTs
            # that already draw scrutiny -- good documentation rescues a
            # marginal case, but can't move an already-easy approval much
            doc_quality_effect = (ops_q - 1.0) * (0.34 if cpt_modifier < 0 else 0.07)
            approval_p = base_approval - chronicity_penalty + cpt_modifier + doc_quality_effect
            approval_p = np.clip(approval_p, 0.05, 0.98)

            auth_submit_date = add_days(intake_date, int(rng.integers(0, 5)))
            auth_decision_days = rng.integers(2, 15)
            auth_decision_date = add_days(auth_submit_date, int(auth_decision_days))
            approved = rng.random() < approval_p

            denial_reason = None
            if not approved:
                denial_reason = rng.choice([
                    "missing_clinical_docs", "not_medically_necessary",
                    "out_of_network", "prior_therapy_not_documented", "coding_mismatch",
                ])

            # --- Storyline 1: BCBS PPO feed breaks in month >= ANOMALY_MONTH_INDEX,
            # silently nulling denial_reason_code for denied claims from that payer ---
            denial_reason_recorded = denial_reason
            if (not approved) and (payer == ANOMALY_PAYER) and (m >= ANOMALY_MONTH_INDEX):
                denial_reason_recorded = None  # data quality break, not a real null

            auths_rows.append({
                "patient_id": patient_id, "clinic_id": clinic_id, "payer": payer,
                "cpt_code": cpt_code, "icd10_code": icd10,
                "auth_submit_date": auth_submit_date,
                "auth_decision_date": auth_decision_date,
                "approved": approved,
                "denial_reason_code": denial_reason_recorded,
                "_true_denial_reason_code_debug": denial_reason,  # kept for validation only
            })

            if not approved:
                continue

            # --- Visits + PT adherence + churn ---
            first_visit_date = add_days(auth_decision_date, int(rng.integers(1, 8)))
            engagement_base = rng.normal(0.6 + payer_cfg.get("engagement_bias", 0.0), 0.18)
            reminders_cohort = clinics.loc[clinics.clinic_id == clinic_id, "reminders_cohort"].iloc[0]
            has_reminders = reminders_cohort == "treatment"

            n_planned_visits = int(np.clip(rng.normal(8 + 10 * chronicity, 3), 2, 24))
            visit_date = first_visit_date
            attended = 0
            for v in range(n_planned_visits):
                if v > 0:
                    gap = cadence_days * rng.normal(1.0, 0.25)
                    visit_date = add_days(visit_date, max(3, int(gap)))
                # only emit visits within the observation window
                if visit_date > month_index_to_date(N_MONTHS):
                    break
                # reminders feature effect only applies after launch month & treatment cohort
                launch_date = month_index_to_date(FEATURE_LAUNCH_MONTH_INDEX)
                reminder_lift = 0.0
                if has_reminders and visit_date >= launch_date:
                    reminder_lift = 0.09  # +9pp attendance probability
                attend_p = np.clip(engagement_base + reminder_lift - 0.03 * v, 0.05, 0.97)
                did_attend = rng.random() < attend_p
                if did_attend:
                    attended += 1
                    visits_rows.append({
                        "patient_id": patient_id, "clinic_id": clinic_id,
                        "visit_number": v + 1, "visit_date": visit_date,
                        "attended": True,
                    })
                else:
                    # a fraction of no-shows still get logged as scheduled-but-missed
                    if rng.random() < 0.4:
                        visits_rows.append({
                            "patient_id": patient_id, "clinic_id": clinic_id,
                            "visit_number": v + 1, "visit_date": visit_date,
                            "attended": False,
                        })
                # churn check: lower chronicity conditions (acute problems) resolve and
                # patients naturally graduate out of care sooner than chronic conditions
                churn_p = (0.14 - 0.06 * engagement_base) * (1.6 - chronicity)
                if attended >= 1 and rng.random() < churn_p:
                    break

            # --- Engagement messages (portal / SMS) ---
            n_msgs = int(np.clip(rng.poisson(4 + 6 * engagement_base), 0, 30))
            for _ in range(n_msgs):
                msg_date = add_days(first_visit_date, int(rng.integers(0, 300)))
                if msg_date > month_index_to_date(N_MONTHS):
                    continue
                messages_rows.append({
                    "patient_id": patient_id, "clinic_id": clinic_id,
                    "message_date": msg_date,
                    "channel": rng.choice(["sms", "portal", "email"], p=[0.5, 0.3, 0.2]),
                    "patient_replied": bool(rng.random() < (0.35 + 0.3 * engagement_base)),
                })

    patients = pd.DataFrame(patients_rows)
    referrals = pd.DataFrame(referrals_rows)
    auths = pd.DataFrame(auths_rows)
    visits = pd.DataFrame(visits_rows)
    messages = pd.DataFrame(messages_rows)

    clinics.to_parquet(out / "clinics.parquet", index=False)
    patients.to_parquet(out / "patients.parquet", index=False)
    referrals.to_parquet(out / "referrals.parquet", index=False)
    auths.drop(columns=["_true_denial_reason_code_debug"]).to_parquet(out / "prior_auths.parquet", index=False)
    visits.to_parquet(out / "visits.parquet", index=False)
    messages.to_parquet(out / "messages.parquet", index=False)

    # Debug/validation copy (not used by downstream pipeline) so we can verify
    # the anomaly was planted correctly.
    auths.to_parquet(out / "_prior_auths_debug_with_truth.parquet", index=False)

    manifest = {
        "seed": cfg.seed,
        "start_date": str(START_DATE),
        "n_months": N_MONTHS,
        "n_clinics": N_CLINICS,
        "n_patients": len(patients),
        "n_referrals": len(referrals),
        "n_auths": len(auths),
        "n_visits": len(visits),
        "n_messages": len(messages),
        "anomaly_payer": ANOMALY_PAYER,
        "anomaly_month": str(month_index_to_date(ANOMALY_MONTH_INDEX)),
        "feature_launch_month": str(month_index_to_date(FEATURE_LAUNCH_MONTH_INDEX)),
        "broken_intake_clinic": CLINIC_INTAKE_BROKEN,
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print("Generated:")
    for k, v in manifest.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default="../data/raw")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(GenConfig(seed=args.seed, out_dir=Path(args.out)))
