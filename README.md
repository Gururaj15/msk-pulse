# MSK Pulse

**Product and operational analytics for a musculoskeletal (MSK) clinic network — plus a prior-authorization denial-risk model that acts on what the analytics found.**

MSK Pulse is an end-to-end project built around a simulated 12-clinic MSK provider network: referrals, intake, prior authorizations, visits, PT adherence, and patient engagement over 24 months. It answers the kind of open-ended operational questions a product/ops-facing data science team owns — where patients drop off, how cohorts retain, whether a feature launch worked, why one clinic underperforms — and then builds a model to act on the biggest finding.

**Live demo (dashboard):** https://msk-pulse.streamlit.app
**Live scoring API (Hugging Face Space):** https://huggingface.co/spaces/gururaj09/msk-pulse-api
**Repository:** https://github.com/Gururaj15/msk-pulse

> All data in this repository is synthetic — see [Data note](#data-note) below.

---

## Table of contents

- [What this project is](#what-this-project-is)
- [The story](#the-story)
- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [What's in each analysis](#whats-in-each-analysis)
- [Running it locally](#running-it-locally)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Clone the repo](#2-clone-the-repo)
  - [3. Create and activate a virtual environment](#3-create-and-activate-a-virtual-environment)
  - [4. Install dependencies](#4-install-dependencies)
  - [5. Run the full pipeline](#5-run-the-full-pipeline)
  - [6. Run the scoring API locally](#6-run-the-scoring-api-locally)
  - [7. Run the dashboard locally](#7-run-the-dashboard-locally)
  - [8. Run tests and lint](#8-run-tests-and-lint)
- [Environment variables](#environment-variables)
- [The model](#the-model)
- [Deployment](#deployment)
- [Continuous integration](#continuous-integration)
- [Data note](#data-note)
- [License](#license)

---

## What this project is

A health-tech operations team needs two things at once: analytics that explain *why* something is happening, and a model that acts on the biggest finding in production. This project builds both, on top of one shared, versioned warehouse, so the two halves stay consistent with each other instead of drifting apart the way a slide-deck analysis and a separately-built model usually do.

Concretely, this repo contains:

- A **synthetic data generator** for a 12-clinic MSK network — patients, referrals, intake, prior authorizations, visits, PT adherence, and engagement events over 24 months, with three intentionally planted scenarios (a data-quality break, a feature launch, and an underperforming clinic) for the analyses to discover.
- A **DuckDB + dbt warehouse** (staging → marts) with data tests, so every downstream number traces back to a tested, documented model instead of an ad-hoc query.
- A **metrics dictionary** — metric definitions live once, in YAML, and get rendered to Markdown docs, so "approval rate" means the same thing on every dashboard and in every analysis.
- **Five analyses**, each a `run.py` that produces charts and a written memo: a conversion funnel, cohort/retention analysis, a properly-measured feature launch (difference-in-differences, not a naive before/after), a data-quality anomaly postmortem, and an open-ended investigation into one underperforming clinic.
- A **prior-authorization denial-risk model** (XGBoost, probability-calibrated, SHAP-explained) trained on the warehouse, motivated directly by what the funnel analysis found.
- A **live scoring API** (Gradio Space, with an alternative FastAPI + Docker path also included) and a **Streamlit ops dashboard** that calls it, so a reviewer can interact with the whole thing rather than just reading about it.
- A **GitHub Actions CI pipeline** that rebuilds everything from a clean checkout on every push — data generation, warehouse build, analyses, model training, and API tests — as proof the project is actually reproducible, not just something that ran once locally.

## The story

The funnel analysis (`analyses/01_funnel`) finds that prior-authorization denial is the single largest *controllable* drop-off in the patient journey — bigger than intake, and unlike intake, addressable with better documentation rather than patient behavior change. That finding motivates the rest of the repo: a denial-risk model (`model/`) that flags high-risk submissions before they go out, served behind a live API and surfaced in the ops dashboard so staff can act on it at the point of submission.

Everything else in the repo is the supporting analytics infrastructure a team actually needs to trust that finding and act on it: a versioned metrics dictionary so "approval rate" means the same thing on every dashboard, a data-quality monitor that catches a planted payer feed break the same month it starts, a properly-measured feature launch, and an open-ended clinic-level investigation worked from question to root cause.

## Architecture

```
Synthetic data generator  →  DuckDB + dbt warehouse  →  Metrics dictionary
                                      ↓
                     Analytics modules (funnel, cohorts, anomaly, launch, deep-dive)
                                      ↓
                  Prior-auth denial-risk model (XGBoost, calibrated, SHAP-explained)
                                      ↓
                Gradio Space (scoring API + demo)   +   Streamlit ops dashboard
```

The API and dashboard are two separate deployable pieces that talk to each other over HTTP: the dashboard's "Prior-Auth Risk Screen" page calls the deployed Space to score a submission and renders the result, exactly the way a real internal tool would call out to a model service.

## Repository structure

```
msk-pulse/
├── data_generator/       synthetic MSK network data generator (seeded, documented assumptions)
│   └── generate.py
├── warehouse/             dbt project over DuckDB: staging, marts, tests, docs
│   ├── models/
│   ├── tests/
│   ├── dbt_project.yml
│   └── profiles.yml
├── metrics/               metrics dictionary (YAML source + generated Markdown)
│   ├── metrics.yml
│   ├── render_dictionary.py
│   └── METRICS_DICTIONARY.md
├── analyses/               one folder per analysis: run.py + memo.md/postmortem.md + charts
│   ├── 01_funnel/
│   ├── 02_cohorts_retention/
│   ├── 03_feature_launch/
│   ├── 04_anomaly_postmortem/
│   └── 05_clinic_deep_dive/
├── model/                  feature pipeline, training, model card, MLflow tracking
│   ├── train.py
│   └── artifacts/          pipeline.joblib, calibrator.joblib, metadata.json, MODEL_CARD.md
├── api/                    scoring service — two deployable variants
│   ├── gradio_app.py       Gradio Space entrypoint (the one actually deployed)
│   ├── model_loader.py     shared model-loading logic used by both variants
│   ├── main.py              FastAPI service (alternative path, e.g. for a Docker host)
│   ├── schemas.py
│   ├── Dockerfile
│   ├── requirements.txt         deps for the FastAPI/Docker variant
│   ├── requirements-gradio.txt  deps for the Gradio Space variant
│   └── tests/
├── dashboard/               Streamlit ops dashboard
│   ├── app.py
│   └── requirements.txt
├── .github/workflows/       CI: lint, dbt build, analyses, training, API tests
├── requirements.txt          full dependency set for local development
├── DEPLOY.md                 step-by-step deployment instructions
└── LICENSE
```

## What's in each analysis

| Question | Where | Method |
|---|---|---|
| Where do patients actually drop off? | [`analyses/01_funnel`](analyses/01_funnel/memo.md) | Stage-by-stage conversion funnel |
| How does retention vary by cohort and payer? | [`analyses/02_cohorts_retention`](analyses/02_cohorts_retention/memo.md) | Cohort tables, Kaplan–Meier survival curves |
| Did the appointment-reminders feature work? | [`analyses/03_feature_launch`](analyses/03_feature_launch/memo.md) | Difference-in-differences, with CUPED variance reduction |
| Why did a data-quality metric suddenly break? | [`analyses/04_anomaly_postmortem`](analyses/04_anomaly_postmortem/postmortem.md) | Root-cause postmortem from a dbt data-quality test firing |
| Why is one clinic underperforming? | [`analyses/05_clinic_deep_dive`](analyses/05_clinic_deep_dive/memo.md) | Open-ended investigation from symptom to operational root cause |
| What are the core metrics, precisely defined? | [`metrics/METRICS_DICTIONARY.md`](metrics/METRICS_DICTIONARY.md) | Versioned YAML → generated docs |
| Can we flag high-denial-risk auths before submission? | [`model/artifacts/MODEL_CARD.md`](model/artifacts/MODEL_CARD.md), served via [`api/`](api/) | Calibrated XGBoost + SHAP |

---

## Running it locally

These instructions cover **Windows (Command Prompt)** as the primary path, with the **macOS/Linux (bash)** equivalent given alongside every command that differs. There is no `make` dependency required — every step can be run directly.

### 1. Prerequisites

- Python 3.11 or newer, available on your PATH (`python --version` should print 3.11+)
- Git

### 2. Clone the repo

**Windows (cmd):**
```bat
git clone https://github.com/Gururaj15/msk-pulse.git
cd msk-pulse
```

**macOS/Linux (bash):**
```bash
git clone https://github.com/Gururaj15/msk-pulse.git
cd msk-pulse
```

### 3. Create and activate a virtual environment

**Windows (cmd):**
```bat
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux (bash):**
```bash
python3 -m venv venv
source venv/bin/activate
```

Your prompt should now be prefixed with `(venv)`. Every command below assumes the virtual environment is active.

### 4. Install dependencies

Same command on every OS, once the virtual environment is active:

```bat
pip install -r requirements.txt
```

### 5. Run the full pipeline

Run these five steps in order — each one depends on the output of the one before it. Commands are identical on Windows cmd and bash except for `cd` chaining, so both are shown together; on Windows run each `cd` on its own line if `&&` chaining doesn't behave in your shell.

**Step 5a — generate the synthetic data:**
```bat
python data_generator/generate.py --out data/raw --seed 42
```

**Step 5b — build the warehouse (DuckDB + dbt):**
```bat
cd warehouse
dbt build --profiles-dir .
cd ..
```

**Step 5c — render the metrics dictionary:**
```bat
cd metrics
python render_dictionary.py
cd ..
```

**Step 5d — run each analysis** (repeat for all five folders):
```bat
cd analyses\01_funnel
python run.py
cd ..\..

cd analyses\02_cohorts_retention
python run.py
cd ..\..

cd analyses\03_feature_launch
python run.py
cd ..\..

cd analyses\04_anomaly_postmortem
python run.py
cd ..\..

cd analyses\05_clinic_deep_dive
python run.py
cd ..\..
```
(On macOS/Linux, replace the backslashes in the `cd` paths with forward slashes, e.g. `cd analyses/01_funnel`.)

Each `run.py` writes its charts and a written memo (`memo.md` or `postmortem.md`) into its own folder.

**Step 5e — train the model:**
```bat
cd model
python train.py
cd ..
```
This writes `pipeline.joblib`, `calibrator.joblib`, `metadata.json`, and `MODEL_CARD.md` into `model/artifacts/`, and logs the run to a local MLflow tracking store (`model/artifacts/mlflow.db`).

### 6. Run the scoring API locally

The project ships two interchangeable ways to serve the trained model — pick one.

**Option A — Gradio (the one actually deployed):**
```bat
cd api
python gradio_app.py
```
Opens at `http://localhost:7860`. This gives you both an interactive demo page and a callable API (`/call/score` over plain HTTP, or via `gradio_client.Client(...)` in Python).

**Option B — FastAPI (alternative path, e.g. for a Docker-capable host):**
```bat
cd api
uvicorn main:app --reload --port 8000
```
Opens at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

### 7. Run the dashboard locally

In a **second terminal**, with the virtual environment activated again:

**Windows (cmd):**
```bat
venv\Scripts\activate
cd dashboard
streamlit run app.py
```

**macOS/Linux (bash):**
```bash
source venv/bin/activate
cd dashboard
streamlit run app.py
```

Opens at `http://localhost:8501`. By default the dashboard's Prior-Auth Risk Screen page tries to reach a locally running Gradio instance at `http://localhost:7860` — if you're running Option A from step 6, this works out of the box. To point it at the deployed Space instead, set the `GRADIO_SPACE_URL` environment variable first (see below).

### 8. Run tests and lint

```bat
cd api
pytest tests/ -v
cd ..
ruff check .
```

---

## Environment variables

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `GRADIO_SPACE_URL` | `dashboard/app.py` | `http://localhost:7860` | Where the dashboard looks for the scoring service. Set this to a Hugging Face Space id (e.g. `gururaj09/msk-pulse-api`) to point the dashboard at a deployed Space instead of a local instance. |

**Setting it locally, Windows (cmd), before running the dashboard:**
```bat
set GRADIO_SPACE_URL=gururaj09/msk-pulse-api
streamlit run app.py
```

**Setting it locally, macOS/Linux (bash):**
```bash
export GRADIO_SPACE_URL=gururaj09/msk-pulse-api
streamlit run app.py
```

When deployed to Streamlit Community Cloud, this is set as a secret in the app's settings instead — see [DEPLOY.md](DEPLOY.md).

---

## The model

A calibrated XGBoost classifier predicts the probability a prior-authorization submission will be denied, trained on a time-based train/calibration/test split (to avoid leaking future information into training). Predicted probabilities are calibrated with isotonic regression so a "20% denial risk" score is meaningfully close to a true 20% empirical rate, not just a ranking score. Each prediction is explained with SHAP, surfacing the top features pushing that specific submission's risk up or down (payer, CPT code, ICD-10 code, clinic operations quality, submission timing, and patient demographics).

Full details, exact metrics, and documented limitations are in the auto-generated [`model/artifacts/MODEL_CARD.md`](model/artifacts/MODEL_CARD.md) after running `model/train.py` — performance is deliberately reported as-is rather than tuned to look impressive, since a defensible, honestly-reported model is more useful in a portfolio than an inflated one.

## Deployment

- **Scoring API** — deployed as a **Gradio Space** on Hugging Face (`api/gradio_app.py`, copied to the Space repo root as `app.py`). A Gradio Space gives both a live interactive demo page and an automatically-exposed callable API from the same app, with no container build required. The equivalent **FastAPI + Docker** service (`api/main.py`, `api/Dockerfile`) is also fully built, tested, and included in the repo as an alternative path for any Docker-capable host (Render, Railway, Fly.io, a self-hosted box, or a Hugging Face Docker Space on accounts with that tier available).
- **Dashboard** — deployed on **Streamlit Community Cloud**, pointed at this repo with `dashboard/app.py` as the entrypoint and the `GRADIO_SPACE_URL` secret set to the deployed Space's id.
- **Docs** — the metrics dictionary and dbt-generated docs can be published via GitHub Pages; see [DEPLOY.md](DEPLOY.md) for the full step-by-step for every piece above, including exact commands.

## Continuous integration

Every push to `main` (and every pull request against it) triggers a GitHub Actions workflow (`.github/workflows/ci.yml`) that rebuilds the entire project from a clean checkout: lints with ruff, regenerates the synthetic data, builds the dbt warehouse, renders the metrics dictionary, runs all five analyses end to end, trains the model, and runs the API test suite. This is meant as evidence the pipeline is genuinely reproducible from nothing but the repo and a Python environment — not something that only happened to work once on one machine.

## Data note

Every record in this repository is synthetically generated (`data_generator/generate.py`, seeded for reproducibility). Base approval and utilization rates are loosely calibrated to public CMS/claims statistics, but no real patient, clinic, or payer data is used anywhere in this project. The generator's causal assumptions (which payer/CPT/clinic factors drive approval, retention, and engagement) are documented inline in the generator source and exist specifically so the downstream analyses have real, discoverable patterns to find — including three intentionally planted scenarios: a payer feed data-quality break, a feature launch, and an underperforming clinic.

## License

MIT — see [LICENSE](LICENSE).