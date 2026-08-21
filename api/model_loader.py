"""Loads the trained pipeline/calibrator/metadata once at process start."""
import json
from pathlib import Path

import joblib
import numpy as np
import shap

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "model" / "artifacts"

CATEGORICAL_FEATURES = ["payer", "condition", "icd10_code", "cpt_code", "clinic_id", "sex"]
NUMERIC_FEATURES = ["age", "ops_quality", "submit_month_sin", "submit_month_cos"]

# Approximate ops_quality per clinic used at inference time, since the caller
# only sends clinic_id, not the clinic's internal quality score. In a real
# deployment this would be looked up from the clinic master table; here we
# read it once from the same parquet the model was trained on.
_CLINIC_OPS_QUALITY: dict[str, float] | None = None


class ModelBundle:
    def __init__(self):
        if not ARTIFACTS_DIR.exists():
            raise FileNotFoundError(
                f"{ARTIFACTS_DIR} not found. Run `python model/train.py` first."
            )
        self.pipeline = joblib.load(ARTIFACTS_DIR / "pipeline.joblib")
        self.calibrator = joblib.load(ARTIFACTS_DIR / "calibrator.joblib")
        with open(ARTIFACTS_DIR / "metadata.json") as f:
            self.metadata = json.load(f)
        self.threshold = self.metadata["denial_risk_threshold"]
        self.version = self.metadata["model_version"]

        self._pre = self.pipeline.named_steps["pre"]
        self._clf = self.pipeline.named_steps["clf"]
        self._explainer = shap.TreeExplainer(self._clf)
        self._feature_names = list(
            self._pre.named_transformers_["cat"].get_feature_names_out(CATEGORICAL_FEATURES)
        ) + NUMERIC_FEATURES
        self._clinic_quality = self._load_clinic_quality()

    def _load_clinic_quality(self) -> dict[str, float]:
        global _CLINIC_OPS_QUALITY
        if _CLINIC_OPS_QUALITY is not None:
            return _CLINIC_OPS_QUALITY
        try:
            import pandas as pd
            clinics_path = Path(__file__).resolve().parent.parent / "data" / "raw" / "clinics.parquet"
            df = pd.read_parquet(clinics_path)
            _CLINIC_OPS_QUALITY = dict(zip(df["clinic_id"], df["ops_quality"]))
        except Exception:
            # fallback: assume average quality if the raw data isn't shipped
            # alongside the API deployment (e.g. HF Spaces image without data/)
            _CLINIC_OPS_QUALITY = {}
        return _CLINIC_OPS_QUALITY

    def ops_quality_for(self, clinic_id: str) -> float:
        return self._clinic_quality.get(clinic_id, 1.0)

    def predict(self, row: dict) -> dict:
        import pandas as pd
        X = pd.DataFrame([row])[CATEGORICAL_FEATURES + NUMERIC_FEATURES]

        approval_prob = float(self.calibrator.predict_proba(X)[0, 1])
        denial_risk = 1 - approval_prob
        high_risk = denial_risk >= self.threshold

        X_transformed = self._pre.transform(X)
        shap_values = self._explainer.shap_values(X_transformed)[0]
        # shap_values here explain P(approved) from the base xgb model;
        # flip sign so positive = increases denial risk, for a UI that's
        # about denial risk rather than approval probability.
        denial_shap = -shap_values
        order = np.argsort(-np.abs(denial_shap))[:5]
        top_factors = [
            {
                "feature": self._feature_names[i],
                "direction": "increases_denial_risk" if denial_shap[i] > 0 else "decreases_denial_risk",
                "magnitude": round(float(abs(denial_shap[i])), 4),
            }
            for i in order
        ]

        return {
            "approval_probability": round(approval_prob, 4),
            "denial_risk_score": round(denial_risk, 4),
            "high_risk_flag": bool(high_risk),
            "risk_threshold_used": round(self.threshold, 4),
            "top_risk_factors": top_factors,
            "model_version": self.version,
        }


_bundle: ModelBundle | None = None


def get_model_bundle() -> ModelBundle:
    global _bundle
    if _bundle is None:
        _bundle = ModelBundle()
    return _bundle
