"""
Prior-auth denial-risk scoring API.

Wraps the trained pipeline in a REST endpoint that accepts a FHIR-shaped
prior-auth request and returns a calibrated approval probability, a
denial-risk flag, and the top SHAP-based risk factors -- decision support
for clinic ops staff reviewing a submission before it goes out.
"""
import math
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from model_loader import get_model_bundle
from schemas import PriorAuthRequest, PriorAuthResponse

app = FastAPI(
    title="MSK Pulse — Prior-Auth Risk API",
    description="Predicts prior-authorization denial risk before submission.",
    version="1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo project — restrict to known origins in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/model-info")
def model_info():
    bundle = get_model_bundle()
    return bundle.metadata


@app.post("/score", response_model=PriorAuthResponse)
def score(req: PriorAuthRequest):
    try:
        bundle = get_model_bundle()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    submit_date = req.submit_date or date.today()
    month = submit_date.month
    row = {
        "payer": req.payer,
        "condition": req.condition,
        "icd10_code": req.icd10_code,
        "cpt_code": req.cpt_code,
        "clinic_id": req.clinic_id,
        "sex": req.patient.sex,
        "age": req.patient.age,
        "ops_quality": bundle.ops_quality_for(req.clinic_id),
        "submit_month_sin": math.sin(2 * math.pi * month / 12),
        "submit_month_cos": math.cos(2 * math.pi * month / 12),
    }
    try:
        result = bundle.predict(row)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not score request: {e}")
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
