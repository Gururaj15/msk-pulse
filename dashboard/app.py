"""
MSK Pulse ops dashboard (Streamlit).

Four pages: Executive Overview, Funnel, Cohorts & Retention, and Prior-Auth
Risk Screen (calls the live scoring model via a Gradio Space). Reads
directly from the dbt-built DuckDB warehouse -- run
`dbt build --profiles-dir .` from warehouse/ before launching this app.

Run: streamlit run app.py
"""
import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from gradio_client import Client

HERE = Path(__file__).resolve().parent
WAREHOUSE_DB = HERE.parent / "warehouse" / "msk_pulse.duckdb"
METRICS_YML = HERE.parent / "metrics" / "metrics.yml"

# The deployed Gradio Space that serves the scoring model (see
# api/gradio_app.py and DEPLOY.md). Defaults to a locally-running
# `python gradio_app.py` instance; override with the GRADIO_SPACE_URL env
# var once deployed, e.g. "https://<hf-username>-msk-pulse-api.hf.space"
# or the shorthand "<hf-username>/msk-pulse-api".
GRADIO_SPACE_URL = os.environ.get("GRADIO_SPACE_URL", "http://localhost:7860")


@st.cache_resource
def get_scoring_client():
    return Client(GRADIO_SPACE_URL)

st.set_page_config(page_title="MSK Pulse", page_icon="🦴", layout="wide")

ACCENT = "#0E7C6B"
SLATE = "#3D5A80"
AMBER = "#A8700D"
MUTED = "#94A6A1"


@st.cache_resource
def get_con():
    if not WAREHOUSE_DB.exists():
        st.error(
            f"Warehouse not found at `{WAREHOUSE_DB}`. Run `dbt build --profiles-dir .` "
            f"from the `warehouse/` folder first."
        )
        st.stop()
    os.chdir(WAREHOUSE_DB.parent)  # so source-view relative parquet paths resolve
    return duckdb.connect(str(WAREHOUSE_DB.name), read_only=True)


@st.cache_data(ttl=600)
def load_journey() -> pd.DataFrame:
    return get_con().execute("select * from main_marts.patient_journey").df()


@st.cache_data(ttl=600)
def load_clinic_metrics() -> pd.DataFrame:
    return get_con().execute("select * from main_marts.clinic_monthly_metrics").df()


@st.cache_data(ttl=600)
def load_auth_facts() -> pd.DataFrame:
    return get_con().execute("select * from main_marts.auth_facts").df()


def kpi_row(items: list[tuple[str, str, str]]):
    cols = st.columns(len(items))
    for col, (label, value, delta) in zip(cols, items):
        col.metric(label, value, delta)


# ---------------------------------------------------------------- Pages ----

def page_overview():
    st.title("Executive overview")
    st.caption("Core metrics, as defined in `metrics/metrics.yml` — the single source of truth.")

    j = load_journey()
    max_date = pd.to_datetime(j["referral_date"]).max()
    censored_cutoff = max_date - pd.Timedelta(days=30)
    j_scoreable = j[pd.to_datetime(j["referral_date"]) <= censored_cutoff]

    intake_rate = j_scoreable["did_intake"].mean()
    approved_mask = j_scoreable["did_submit_auth"] & j_scoreable["auth_approved"].fillna(False)
    submitted_mask = j_scoreable["did_submit_auth"]
    approval_rate = approved_mask.sum() / submitted_mask.sum()
    visit_conv = j_scoreable.loc[approved_mask, "did_first_visit"].mean()
    retention_pool = j_scoreable[j_scoreable["did_first_visit"]]
    retention_90d = retention_pool["active_at_90_days"].mean()

    kpi_row([
        ("Intake rate", f"{intake_rate*100:.1f}%", None),
        ("Auth approval rate", f"{approval_rate*100:.1f}%", None),
        ("Visit conversion", f"{visit_conv*100:.1f}%", None),
        ("90-day retention", f"{retention_90d*100:.1f}%", None),
    ])

    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Approval rate by payer")
        by_payer = (
            j_scoreable[j_scoreable.did_submit_auth]
            .groupby("payer")
            .apply(lambda g: g["auth_approved"].mean(), include_groups=False)
            .sort_values()
        )
        fig = px.bar(by_payer, orientation="h", labels={"value": "Approval rate", "payer": ""},
                     color_discrete_sequence=[SLATE])
        fig.update_layout(showlegend=False, xaxis_tickformat=".0%")
        st.plotly_chart(fig, width='stretch')

    with c2:
        st.subheader("Referral volume trend")
        r = j.copy()
        r["referral_month"] = pd.to_datetime(r["referral_date"]).dt.to_period("M").astype(str)
        vol = r.groupby("referral_month").size().reset_index(name="n_referrals")
        fig = px.line(vol, x="referral_month", y="n_referrals", markers=True,
                       color_discrete_sequence=[ACCENT])
        fig.update_xaxes(tickangle=90, tickfont=dict(size=8))
        st.plotly_chart(fig, width='stretch')

    st.markdown("---")
    st.subheader("Clinic scorecard")
    cm = load_clinic_metrics()
    latest_month = cm["referral_month"].max()
    latest = cm[cm.referral_month == latest_month].sort_values("intake_rate")
    show = latest[["clinic_name", "n_referrals", "intake_rate", "auth_approval_rate",
                    "visit_conversion_rate", "retention_90d_rate"]].copy()
    for c in ["intake_rate", "auth_approval_rate", "visit_conversion_rate", "retention_90d_rate"]:
        show[c] = (show[c] * 100).round(1)
    show.columns = ["Clinic", "Referrals", "Intake %", "Approval %", "Visit conv. %", "90d retention %"]
    st.dataframe(show, width='stretch', hide_index=True)
    st.caption(f"Most recent complete-ish month shown: {latest_month}")


def page_funnel():
    st.title("Patient journey funnel")
    j = load_journey()
    max_date = pd.to_datetime(j["referral_date"]).max()
    j = j[pd.to_datetime(j["referral_date"]) <= max_date - pd.Timedelta(days=30)]

    stages = ["referred", "intake", "auth_submitted", "auth_approved", "first_visit"]
    counts = [
        len(j), j["did_intake"].sum(), j["did_submit_auth"].sum(),
        (j["did_submit_auth"] & j["auth_approved"].fillna(False)).sum(),
        j["did_first_visit"].sum(),
    ]
    fig = go.Figure(go.Funnel(y=stages, x=counts, marker={"color": ACCENT}))
    st.plotly_chart(fig, width='stretch')

    st.subheader("Drop-off by payer at the auth stage")
    submitted = j[j.did_submit_auth]
    by_payer = submitted.groupby("payer")["auth_approved"].mean().sort_values()
    fig2 = px.bar(by_payer, orientation="h", color_discrete_sequence=[AMBER],
                  labels={"value": "Approval rate", "payer": ""})
    fig2.update_layout(showlegend=False, xaxis_tickformat=".0%")
    st.plotly_chart(fig2, width='stretch')

    st.info("Full write-up: `analyses/01_funnel/memo.md`")


def page_cohorts():
    st.title("Cohorts & retention")
    j = load_journey()
    visited = j[j.did_first_visit].copy()
    visited["first_visit_date"] = pd.to_datetime(visited["first_visit_date"])
    visited["cohort_month"] = visited["first_visit_date"].dt.to_period("M").astype(str)

    st.subheader("90-day retention by acquisition cohort")
    cohort_ret = visited.groupby("cohort_month")["active_at_90_days"].mean().reset_index()
    fig = px.bar(cohort_ret, x="cohort_month", y="active_at_90_days",
                 color_discrete_sequence=[ACCENT])
    fig.update_layout(yaxis_tickformat=".0%")
    fig.update_xaxes(tickangle=90, tickfont=dict(size=8))
    st.plotly_chart(fig, width='stretch')

    st.subheader("Retention by payer")
    by_payer = visited.groupby("payer")["active_at_90_days"].mean().sort_values()
    fig2 = px.bar(by_payer, orientation="h", color_discrete_sequence=[SLATE],
                  labels={"value": "90-day retention", "payer": ""})
    fig2.update_layout(showlegend=False, xaxis_tickformat=".0%")
    st.plotly_chart(fig2, width='stretch')

    st.info("Full survival-curve analysis (Kaplan-Meier): `analyses/02_cohorts_retention/memo.md`")


def page_prior_auth():
    st.title("Prior-auth risk screen")
    st.caption("Calls the live scoring model (Gradio Space) before a submission goes out.")

    with st.form("score_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            age = st.number_input("Patient age", min_value=18, max_value=95, value=55)
            sex = st.selectbox("Sex", ["F", "M"])
        with c2:
            payer = st.selectbox("Payer", [
                "Aetna Commercial", "UnitedHealthcare", "Cigna",
                "Medicare Part B", "Medicaid (State)", "BCBS PPO",
            ])
            clinic_id = st.selectbox("Clinic", [f"Clinic_{i:02d}" for i in range(1, 13)])
        with c3:
            condition = st.selectbox("Condition", [
                "Low back pain", "Knee osteoarthritis", "Rotator cuff injury",
                "Cervical radiculopathy", "Post-op knee (ACL)", "Hip osteoarthritis",
                "Plantar fasciitis", "Lateral epicondylitis", "Post-op shoulder",
            ])
            cpt_code = st.text_input("CPT code", value="97110")
        icd10_code = st.text_input("ICD-10 code", value="M54.5")
        submitted = st.form_submit_button("Score submission")

    if submitted:
        try:
            client = get_scoring_client()
            _summary_md, result = client.predict(
                int(age), sex, payer, clinic_id, condition, icd10_code, cpt_code,
                api_name="/score",
            )
        except Exception as e:
            st.error(
                f"Couldn't reach the scoring model at `{GRADIO_SPACE_URL}`. "
                f"Set the `GRADIO_SPACE_URL` environment variable once the Space is deployed. ({e})"
            )
            return

        risk_pct = result["denial_risk_score"] * 100
        c1, c2 = st.columns([1, 2])
        with c1:
            if result["high_risk_flag"]:
                st.error(f"⚠ High denial risk: **{risk_pct:.0f}%**")
            else:
                st.success(f"Low denial risk: **{risk_pct:.0f}%**")
            st.metric("Approval probability", f"{result['approval_probability']*100:.0f}%")
            st.caption(f"Threshold: {result['risk_threshold_used']*100:.0f}% · model {result['model_version']}")
        with c2:
            st.subheader("Top risk factors")
            factors = pd.DataFrame(result["top_risk_factors"])
            factors["magnitude"] = factors["magnitude"].round(3)
            factors["direction"] = factors["direction"].str.replace("_", " ")
            st.dataframe(factors, width='stretch', hide_index=True)


PAGES = {
    "Executive overview": page_overview,
    "Funnel": page_funnel,
    "Cohorts & retention": page_cohorts,
    "Prior-auth risk screen": page_prior_auth,
}

st.sidebar.title("MSK Pulse")
choice = st.sidebar.radio("View", list(PAGES.keys()))
st.sidebar.markdown("---")
st.sidebar.caption("Metrics dictionary: `metrics/METRICS_DICTIONARY.md`")
PAGES[choice]()