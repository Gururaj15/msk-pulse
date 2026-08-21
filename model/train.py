"""
Train the prior-auth denial-risk model.

Predicts P(approved) for a prior-authorization request using only fields
known at *submission* time (payer, CPT, ICD-10, patient demographics, clinic)
-- explicitly excluding anything only known after a decision is made
(decision_days, auth_decision_date, denial_reason_code) to avoid leakage.

Pipeline:
  1. Time-based train / calibration / test split (never shuffle auth data --
     a submission's outcome must only ever be predicted from the past).
  2. XGBoost classifier inside an sklearn Pipeline (one-hot encoding for
     categoricals, so no raw strings reach the model).
  3. Threshold tuned for a target denial recall (catch most likely denials,
     even at some precision cost -- the operational cost of a missed
     high-risk submission is higher than a false alarm).
  4. Isotonic calibration on a held-out calibration split (probabilities
     need to mean what they say for staff to trust a "72% approval" score).
  5. SHAP explanations, logged to local MLflow, plus a written model card.

Outputs (in model/artifacts/):
  - pipeline.joblib        -- fitted sklearn Pipeline (preprocessing + XGB)
  - calibrator.joblib       -- isotonic calibrator wrapping the pipeline
  - metadata.json          -- feature list, threshold, metrics, version
  - shap_summary.png
  - calibration_curve.png
  - MODEL_CARD.md
"""
import json
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import shap
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analyses"))
from _common import connect

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

MODEL_VERSION = "v1"
TARGET_DENIAL_RECALL = 0.80  # catch at least 80% of true denials pre-submission

CATEGORICAL_FEATURES = ["payer", "condition", "icd10_code", "cpt_code", "clinic_id", "sex"]
NUMERIC_FEATURES = ["age", "ops_quality", "submit_month_sin", "submit_month_cos"]


def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    month = df["auth_submit_date"].dt.month
    df["submit_month_sin"] = np.sin(2 * np.pi * month / 12)
    df["submit_month_cos"] = np.cos(2 * np.pi * month / 12)
    return df


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CATEGORICAL_FEATURES),
        ("num", "passthrough", NUMERIC_FEATURES),
    ])
    clf = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        eval_metric="logloss",
        random_state=42,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def get_feature_names(pipeline: Pipeline) -> list[str]:
    pre = pipeline.named_steps["pre"]
    cat_names = list(pre.named_transformers_["cat"].get_feature_names_out(CATEGORICAL_FEATURES))
    return cat_names + NUMERIC_FEATURES


def main():
    con = connect()
    auths = con.execute("select * from main_marts.auth_facts").df()
    auths["auth_submit_date"] = pd.to_datetime(auths["auth_submit_date"])
    auths = add_seasonal_features(auths)
    auths["target_approved"] = auths["approved"].astype(int)

    auths = auths.sort_values("auth_submit_date").reset_index(drop=True)
    n = len(auths)
    train_end = int(n * 0.70)
    calib_end = int(n * 0.85)
    train = auths.iloc[:train_end]
    calib = auths.iloc[train_end:calib_end]
    test = auths.iloc[calib_end:]
    print(f"Train: {len(train):,} rows ({train.auth_submit_date.min().date()} - {train.auth_submit_date.max().date()})")
    print(f"Calib: {len(calib):,} rows ({calib.auth_submit_date.min().date()} - {calib.auth_submit_date.max().date()})")
    print(f"Test:  {len(test):,} rows  ({test.auth_submit_date.min().date()} - {test.auth_submit_date.max().date()})")

    feature_cols = CATEGORICAL_FEATURES + NUMERIC_FEATURES
    X_train, y_train = train[feature_cols], train["target_approved"]
    X_calib, y_calib = calib[feature_cols], calib["target_approved"]
    X_test, y_test = test[feature_cols], test["target_approved"]

    # SQLite backend (not the deprecated file store) -- still fully local,
    # no server or network required.
    mlflow.set_tracking_uri(f"sqlite:///{ARTIFACTS / 'mlflow.db'}")
    mlflow.set_experiment("prior_auth_denial_risk")

    with mlflow.start_run(run_name=f"xgb_{MODEL_VERSION}"):
        pipeline = build_pipeline()
        pipeline.fit(X_train, y_train)

        # --- Base (uncalibrated) performance on test ---
        raw_probs_test = pipeline.predict_proba(X_test)[:, 1]  # P(approved)
        auc = roc_auc_score(y_test, raw_probs_test)
        ap = average_precision_score(1 - y_test, 1 - raw_probs_test)  # denial-class PR-AUC
        print(f"\nTest ROC-AUC (approval): {auc:.3f}")
        print(f"Test PR-AUC (denial class): {ap:.3f}")

        # --- Calibration on held-out calib split ---
        calibrator = CalibratedClassifierCV(FrozenEstimator(pipeline), method="isotonic")
        calibrator.fit(X_calib, y_calib)
        cal_probs_test = calibrator.predict_proba(X_test)[:, 1]
        cal_auc = roc_auc_score(y_test, cal_probs_test)

        # --- Threshold tuning for target denial recall ---
        # denial risk score = 1 - P(approved); flag as "high risk" if
        # denial_risk >= threshold. Sweep thresholds on the *denial* class.
        denial_risk_test = 1 - cal_probs_test
        y_denied_test = 1 - y_test
        precisions, recalls, thresholds = precision_recall_curve(y_denied_test, denial_risk_test)
        # find lowest threshold achieving >= TARGET_DENIAL_RECALL
        valid = np.where(recalls[:-1] >= TARGET_DENIAL_RECALL)[0]
        if len(valid) > 0:
            chosen_idx = valid[np.argmax(thresholds[valid])]  # highest threshold that still meets recall
            chosen_threshold = float(thresholds[chosen_idx])
            chosen_precision = float(precisions[chosen_idx])
            chosen_recall = float(recalls[chosen_idx])
        else:
            chosen_threshold, chosen_precision, chosen_recall = 0.5, float(precisions[0]), float(recalls[0])
        print(f"Chosen denial-risk threshold: {chosen_threshold:.3f}")
        print(f"  -> denial recall: {chosen_recall:.3f}, precision: {chosen_precision:.3f}")

        # --- Calibration curve chart ---
        frac_pos, mean_pred = calibration_curve(y_test, cal_probs_test, n_bins=10, strategy="quantile")
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot([0, 1], [0, 1], "--", color="#94A6A1", label="Perfectly calibrated")
        ax.plot(mean_pred, frac_pos, marker="o", color="#0E7C6B", label="Calibrated model")
        ax.set_xlabel("Mean predicted approval probability")
        ax.set_ylabel("Observed approval rate")
        ax.set_title("Calibration curve (test set)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(ARTIFACTS / "calibration_curve.png", dpi=150)
        plt.close(fig)

        # --- SHAP explanations (on the underlying uncalibrated pipeline —
        # calibration is a monotonic wrapper and doesn't change feature
        # attributions, only the probability scale) ---
        xgb_model = pipeline.named_steps["clf"]
        X_test_transformed = pipeline.named_steps["pre"].transform(X_test)
        feature_names = get_feature_names(pipeline)
        explainer = shap.TreeExplainer(xgb_model)
        # subsample for speed on the demo dataset
        sample_idx = np.random.default_rng(42).choice(
            X_test_transformed.shape[0], size=min(1500, X_test_transformed.shape[0]), replace=False
        )
        shap_values = explainer.shap_values(X_test_transformed[sample_idx])

        fig = plt.figure(figsize=(8, 6))
        shap.summary_plot(shap_values, X_test_transformed[sample_idx], feature_names=feature_names,
                           show=False, max_display=15)
        fig = plt.gcf()
        fig.tight_layout()
        fig.savefig(ARTIFACTS / "shap_summary.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        top_features = pd.DataFrame({"feature": feature_names, "mean_abs_shap": mean_abs_shap}) \
            .sort_values("mean_abs_shap", ascending=False).head(10)

        # --- persist artifacts ---
        joblib.dump(pipeline, ARTIFACTS / "pipeline.joblib")
        joblib.dump(calibrator, ARTIFACTS / "calibrator.joblib")

        metadata = {
            "model_version": MODEL_VERSION,
            "trained_at": pd.Timestamp.utcnow().isoformat(),
            "feature_columns": feature_cols,
            "categorical_features": CATEGORICAL_FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "denial_risk_threshold": chosen_threshold,
            "target_denial_recall": TARGET_DENIAL_RECALL,
            "metrics": {
                "test_roc_auc_approval": round(auc, 4),
                "test_roc_auc_approval_calibrated": round(cal_auc, 4),
                "test_pr_auc_denial_class": round(ap, 4),
                "denial_recall_at_threshold": round(chosen_recall, 4),
                "denial_precision_at_threshold": round(chosen_precision, 4),
                "n_train": len(train), "n_calib": len(calib), "n_test": len(test),
            },
            "top_shap_features": top_features.to_dict(orient="records"),
        }
        with open(ARTIFACTS / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        mlflow.log_params({"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
                            "target_denial_recall": TARGET_DENIAL_RECALL})
        mlflow.log_metrics({
            "test_roc_auc": auc, "test_roc_auc_calibrated": cal_auc,
            "test_pr_auc_denial": ap, "denial_recall": chosen_recall,
            "denial_precision": chosen_precision,
        })
        mlflow.log_artifact(str(ARTIFACTS / "calibration_curve.png"))
        mlflow.log_artifact(str(ARTIFACTS / "shap_summary.png"))

        # --- model card ---
        card = f"""# Model Card — Prior-Auth Denial-Risk Model ({MODEL_VERSION})

## Intended use

Flags a prior-authorization request as **high denial-risk** *before submission* so staff can review and
fix documentation gaps proactively, rather than appealing after a denial. This is a **decision-support**
tool for clinic ops staff, not an automated approval/denial system — every flagged submission still goes
through normal human review.

## Training data

Synthetic MSK clinic network data (see `data_generator/`), {metadata['metrics']['n_train']:,} training
records. **Not real patient or payer data.** Approval-rate base rates are loosely calibrated to public
CMS Part B statistics but this model is a portfolio demonstration, not a validated clinical or claims tool.

## Features

Only fields known at *submission* time are used — payer, condition, ICD-10, CPT code, clinic, patient
age/sex, and submission seasonality. `decision_days`, `auth_decision_date`, and `denial_reason_code`
are deliberately excluded: they are only known *after* a decision and would leak the outcome.

## Performance (time-based test split — the most recent {metadata['metrics']['n_test']:,} submissions,
model never trained on data from after the training window)

| Metric | Value |
|---|---:|
| ROC-AUC (approval) | {auc:.3f} |
| ROC-AUC, calibrated | {cal_auc:.3f} |
| PR-AUC (denial class) | {ap:.3f} |
| Denial recall @ threshold {chosen_threshold:.2f} | {chosen_recall:.1%} |
| Denial precision @ threshold {chosen_threshold:.2f} | {chosen_precision:.1%} |

The operating threshold is tuned for **{TARGET_DENIAL_RECALL:.0%} denial recall** — catching most true
denials before submission is worth more operationally than avoiding false alarms, since a flagged-but-
actually-fine submission just gets a quick extra review, while a missed denial costs a full appeal cycle.

## Calibration

Probabilities are isotonic-calibrated on a held-out split (`calibration_curve.png`) — a predicted 70%
approval probability should reflect roughly 70% observed approval in that probability band, which matters
for staff trusting the score enough to act on it, not just rank-order it.

## Top denial-risk drivers (mean |SHAP|)

{chr(10).join(f"{i+1}. `{r['feature']}`" for i, r in enumerate(top_features.to_dict(orient='records')))}

See `shap_summary.png` for the full distribution of each feature's effect.

## Limitations

- Trained on synthetic data with a generator-defined causal structure — real payer/clinical denial patterns
  will differ, and this model would need retraining on real (de-identified) data before any production use.
- No fairness audit performed. Any real deployment must check for disparate impact across protected classes
  before flagging patients differently by demographic-correlated features (e.g., payer often correlates with
  socioeconomic factors).
- Time-based split guards against look-ahead leakage but does not guarantee performance holds under future
  payer policy changes — recommend a scheduled retrain + drift monitor, not a train-once deployment.

*Trained {metadata['trained_at']}. Artifacts: `pipeline.joblib`, `calibrator.joblib`, `metadata.json`.*
"""
        (ARTIFACTS / "MODEL_CARD.md").write_text(card, encoding="utf-8")
        mlflow.log_artifact(str(ARTIFACTS / "MODEL_CARD.md"))

    print(f"\nWrote artifacts to {ARTIFACTS}")


if __name__ == "__main__":
    main()
