"""
Tests for the prior-auth scoring API. Covers a valid request, validation
edge cases, and the health/model-info endpoints.

Run from api/: pytest tests/ -v
(requires model/train.py to have been run at least once first)
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "patient": {"age": 58, "sex": "F"},
    "clinic_id": "Clinic_03",
    "payer": "Medicaid (State)",
    "condition": "Post-op knee (ACL)",
    "icd10_code": "Z47.89",
    "cpt_code": "29888",
    "submit_date": "2026-08-15",
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_model_info():
    resp = client.get("/model-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "model_version" in body
    assert "metrics" in body


def test_score_valid_request():
    resp = client.post("/score", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["approval_probability"] <= 1.0
    assert 0.0 <= body["denial_risk_score"] <= 1.0
    assert abs(body["approval_probability"] + body["denial_risk_score"] - 1.0) < 1e-6
    assert isinstance(body["high_risk_flag"], bool)
    assert len(body["top_risk_factors"]) > 0
    assert body["model_version"] == "v1"


def test_score_without_submit_date_defaults_to_today():
    payload = {**VALID_PAYLOAD}
    del payload["submit_date"]
    resp = client.post("/score", json=payload)
    assert resp.status_code == 200


@pytest.mark.parametrize("field,bad_value", [
    ("payer", "Not A Real Payer"),
    ("condition", "Not A Real Condition"),
    ("clinic_id", "Clinic_99"),
])
def test_score_rejects_unknown_categoricals(field, bad_value):
    payload = {**VALID_PAYLOAD, field: bad_value}
    resp = client.post("/score", json=payload)
    assert resp.status_code == 422


def test_score_rejects_invalid_sex():
    payload = {**VALID_PAYLOAD, "patient": {"age": 40, "sex": "X"}}
    resp = client.post("/score", json=payload)
    assert resp.status_code == 422


def test_score_rejects_out_of_range_age():
    payload = {**VALID_PAYLOAD, "patient": {"age": 200, "sex": "F"}}
    resp = client.post("/score", json=payload)
    assert resp.status_code == 422


def test_score_rejects_missing_required_field():
    payload = {**VALID_PAYLOAD}
    del payload["cpt_code"]
    resp = client.post("/score", json=payload)
    assert resp.status_code == 422


def test_score_high_risk_case_flags_correctly():
    # surgical CPT + strict payer + high chronicity condition -> expect a
    # meaningfully higher denial risk than a routine-therapy case
    high_risk_payload = {
        "patient": {"age": 45, "sex": "M"},
        "clinic_id": "Clinic_07",  # lowest ops_quality-adjacent clinic
        "payer": "UnitedHealthcare",
        "condition": "Post-op shoulder",
        "icd10_code": "Z47.89",
        "cpt_code": "23412",
        "submit_date": "2026-08-15",
    }
    low_risk_payload = {
        "patient": {"age": 45, "sex": "M"},
        "clinic_id": "Clinic_04",
        "payer": "Medicare Part B",
        "condition": "Plantar fasciitis",
        "icd10_code": "M72.2",
        "cpt_code": "97110",
        "submit_date": "2026-08-15",
    }
    high_resp = client.post("/score", json=high_risk_payload).json()
    low_resp = client.post("/score", json=low_risk_payload).json()
    assert high_resp["denial_risk_score"] > low_resp["denial_risk_score"]
