"""
Pydantic schemas for the prior-auth scoring API.

The request shape is deliberately FHIR-adjacent (a small, explicit subset of
fields loosely modeled on a FHIR Claim / CoverageEligibilityRequest, not a
full FHIR resource) -- enough to demonstrate the integration pattern a real
EMR-adjacent service would use, without pulling in a full FHIR client library
for a synthetic-data project.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_PAYERS = {
    "Aetna Commercial", "UnitedHealthcare", "Cigna",
    "Medicare Part B", "Medicaid (State)", "BCBS PPO",
}
VALID_CONDITIONS = {
    "Low back pain", "Knee osteoarthritis", "Rotator cuff injury",
    "Cervical radiculopathy", "Post-op knee (ACL)", "Hip osteoarthritis",
    "Plantar fasciitis", "Lateral epicondylitis", "Post-op shoulder",
}
VALID_CLINICS = {f"Clinic_{i:02d}" for i in range(1, 13)}


class PatientRef(BaseModel):
    """Minimal patient demographic block (FHIR Patient-shaped subset)."""
    age: int = Field(..., ge=0, le=120, description="Patient age in years")
    sex: str = Field(..., description="'F' or 'M'")

    @field_validator("sex")
    @classmethod
    def validate_sex(cls, v: str) -> str:
        if v not in ("F", "M"):
            raise ValueError("sex must be 'F' or 'M'")
        return v


class PriorAuthRequest(BaseModel):
    """A prior-authorization scoring request (FHIR Claim-shaped subset)."""
    patient: PatientRef
    clinic_id: str = Field(..., description="e.g. 'Clinic_01'")
    payer: str = Field(..., description="Payer / plan name")
    condition: str = Field(..., description="Clinical condition label")
    icd10_code: str = Field(..., description="ICD-10-CM diagnosis code")
    cpt_code: str = Field(..., description="CPT procedure code being requested")
    submit_date: Optional[date] = Field(
        default=None, description="Submission date; defaults to today if omitted"
    )

    @field_validator("payer")
    @classmethod
    def validate_payer(cls, v: str) -> str:
        if v not in VALID_PAYERS:
            raise ValueError(f"payer must be one of {sorted(VALID_PAYERS)}")
        return v

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str) -> str:
        if v not in VALID_CONDITIONS:
            raise ValueError(f"condition must be one of {sorted(VALID_CONDITIONS)}")
        return v

    @field_validator("clinic_id")
    @classmethod
    def validate_clinic(cls, v: str) -> str:
        if v not in VALID_CLINICS:
            raise ValueError(f"clinic_id must be one of {sorted(VALID_CLINICS)}")
        return v

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "patient": {"age": 58, "sex": "F"},
            "clinic_id": "Clinic_03",
            "payer": "Medicaid (State)",
            "condition": "Post-op knee (ACL)",
            "icd10_code": "Z47.89",
            "cpt_code": "29888",
            "submit_date": "2026-08-15",
        }
    })


class RiskFactor(BaseModel):
    feature: str
    direction: str  # "increases_denial_risk" | "decreases_denial_risk"
    magnitude: float


class PriorAuthResponse(BaseModel):
    approval_probability: float = Field(..., ge=0, le=1)
    denial_risk_score: float = Field(..., ge=0, le=1)
    high_risk_flag: bool
    risk_threshold_used: float
    top_risk_factors: list[RiskFactor]
    model_version: str
