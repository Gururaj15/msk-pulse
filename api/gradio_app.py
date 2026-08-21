"""
Prior-auth denial-risk scoring — Gradio Space version.

Hugging Face Spaces' Docker SDK requires a paid tier on some accounts;
Gradio Spaces are free and, as a bonus, automatically expose a callable API
for every app (via gradio_client or a plain HTTP POST to /call/predict) —
so this one file gives us both a live interactive demo *and* a live API,
with no Docker involved.

Reuses the exact same model_loader.ModelBundle used by the FastAPI service
(api/main.py) — this is not a second model, just a second front door onto
the same trained pipeline.

Local run: python gradio_app.py  (opens at http://localhost:7860)
Deploy: this file must be named `app.py` at the Space repo root (see DEPLOY.md).
"""
import math
from datetime import date

import gradio as gr
from model_loader import get_model_bundle

# Some Hugging Face accounts default free Gradio Spaces to ZeroGPU hardware
# (an on-demand shared GPU pool, still free, no billing). ZeroGPU requires
# at least one function to be marked with @spaces.GPU so it knows which
# call to allocate a GPU for -- this model doesn't actually need a GPU
# (it's a small XGBoost model), the decorator just satisfies that
# requirement so the Space starts. Falls back to a no-op when the `spaces`
# package isn't installed (e.g. running locally with `python gradio_app.py`
# outside a Hugging Face Space), so this file works in both places.
try:
    import spaces
    gpu_decorator = spaces.GPU
except ImportError:
    def gpu_decorator(fn):
        return fn

PAYERS = ["Aetna Commercial", "UnitedHealthcare", "Cigna",
          "Medicare Part B", "Medicaid (State)", "BCBS PPO"]
CONDITIONS = ["Low back pain", "Knee osteoarthritis", "Rotator cuff injury",
              "Cervical radiculopathy", "Post-op knee (ACL)", "Hip osteoarthritis",
              "Plantar fasciitis", "Lateral epicondylitis", "Post-op shoulder"]
CLINICS = [f"Clinic_{i:02d}" for i in range(1, 13)]


@gpu_decorator
def score(age: int, sex: str, payer: str, clinic_id: str, condition: str,
          icd10_code: str, cpt_code: str):
    """Callable both from the Gradio UI and, once deployed, as this Space's
    API endpoint (gradio_client.Client(...).predict(...) with these same
    positional arguments, in this order)."""
    bundle = get_model_bundle()
    submit_date = date.today()
    month = submit_date.month
    row = {
        "payer": payer, "condition": condition, "icd10_code": icd10_code.strip(),
        "cpt_code": cpt_code.strip(), "clinic_id": clinic_id, "sex": sex,
        "age": int(age), "ops_quality": bundle.ops_quality_for(clinic_id),
        "submit_month_sin": math.sin(2 * math.pi * month / 12),
        "submit_month_cos": math.cos(2 * math.pi * month / 12),
    }
    result = bundle.predict(row)

    risk_pct = result["denial_risk_score"] * 100
    label = f"{'⚠ HIGH' if result['high_risk_flag'] else 'Low'} denial risk: {risk_pct:.0f}%"
    factors_md = "\n".join(
        f"{i+1}. **{f['feature']}** — {f['direction'].replace('_', ' ')} (magnitude {f['magnitude']:.3f})"
        for i, f in enumerate(result["top_risk_factors"])
    )
    summary = (
        f"### {label}\n\n"
        f"**Approval probability:** {result['approval_probability']*100:.0f}%\n\n"
        f"**Threshold used:** {result['risk_threshold_used']*100:.0f}% · model {result['model_version']}\n\n"
        f"### Top risk factors\n{factors_md}"
    )
    return summary, result


demo = gr.Interface(
    fn=score,
    inputs=[
        gr.Slider(18, 95, value=55, step=1, label="Patient age"),
        gr.Radio(["F", "M"], value="F", label="Sex"),
        gr.Dropdown(PAYERS, value="Medicaid (State)", label="Payer"),
        gr.Dropdown(CLINICS, value="Clinic_03", label="Clinic"),
        gr.Dropdown(CONDITIONS, value="Post-op knee (ACL)", label="Condition"),
        gr.Textbox(value="Z47.89", label="ICD-10 code"),
        gr.Textbox(value="29888", label="CPT code"),
    ],
    outputs=[
        gr.Markdown(label="Result"),
        gr.JSON(label="Raw response (this is also what the API returns)"),
    ],
    title="MSK Pulse — Prior-Auth Risk Screen",
    description=(
        "Predicts prior-authorization denial risk before submission, using a calibrated "
        "XGBoost model trained on the MSK Pulse synthetic clinic network "
        "(see the full project on GitHub). This same function is callable as an API — "
        "see the 'Use via API' link at the bottom of this page once deployed."
    ),
    flagging_mode="never",
    api_name="score",
)

if __name__ == "__main__":
    demo.launch()