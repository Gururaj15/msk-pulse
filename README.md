# MSK Pulse

**Product and operational analytics for a musculoskeletal (MSK) clinic network — plus a prior-authorization denial-risk model that acts on what the analytics found.**

MSK Pulse is an end-to-end data science project built around a simulated 12-clinic MSK provider network: referrals, intake, prior authorizations, visits, PT adherence, and patient engagement over 24 months. It answers the kind of open-ended operational questions a product/ops-facing data science team owns — where patients drop off, how cohorts retain, whether a feature launch worked, why one clinic underperforms — and then builds a model to act on the biggest finding.

**Live demo:** [dashboard link] · **API:** [API link] · **Write-up:** [Medium series link]

> All data in this repository is synthetic. See `data_generator/README` note below.

## What's here

| Question | Where |
|---|---|
| Where do patients actually drop off? | [`analyses/01_funnel`](analyses/01_funnel/memo.md) |
| How does retention vary by cohort and payer? | [`analyses/02_cohorts_retention`](analyses/02_cohorts_retention/memo.md) |
| Did the appointment-reminders feature work? | [`analyses/03_feature_launch`](analyses/03_feature_launch/memo.md) |
| Why did a data-quality metric suddenly break? | [`analyses/04_anomaly_postmortem`](analyses/04_anomaly_postmortem/postmortem.md) |
| Why is one clinic underperforming? | [`analyses/05_clinic_deep_dive`](analyses/05_clinic_deep_dive/memo.md) |
| What are the core metrics, precisely defined? | [`metrics/METRICS_DICTIONARY.md`](metrics/METRICS_DICTIONARY.md) |
| Can we flag high-denial-risk auths before submission? | [`model/artifacts/MODEL_CARD.md`](model/artifacts/MODEL_CARD.md), served via [`api/`](api/) |

## The story

The funnel analysis (`analyses/01_funnel`) finds that prior-authorization denial is the single largest *controllable* drop-off in the patient journey — bigger than intake, and unlike intake, addressable with better documentation rather than patient behavior change. That finding motivates the rest of the repo: a denial-risk model (`model/`) that flags high-risk submissions before they go out, served behind a live API and surfaced in the ops dashboard so staff can act on it at the point of submission.

Everything else in the repo is the supporting analytics infrastructure a team actually needs to trust that finding and act on it: a versioned metrics dictionary so "approval rate" means the same thing on every dashboard, a data-quality monitor that catches a planted payer feed break the same month it starts, a properly-measured feature launch (diff-in-diff, not a naive before/after), and an open-ended clinic-level investigation worked from question to root cause.

## Architecture

```
Synthetic data generator  →  DuckDB + dbt warehouse  →  Metrics dictionary
                                      ↓
                     Analytics modules (funnel, cohorts, anomaly, launch, deep-dive)
                                      ↓
                  Prior-auth denial-risk model (XGBoost, calibrated, SHAP-explained)
                                      ↓
              FastAPI scoring service   +   Streamlit ops dashboard
```

## Repository structure

```
msk-pulse/
├── data_generator/     synthetic MSK network data (seeded, documented assumptions)
├── warehouse/           dbt project over DuckDB: staging, marts, tests, docs
├── metrics/              metrics dictionary (YAML source + generated Markdown)
├── analyses/             one folder per analysis: run.py + memo.md + charts
│   ├── 01_funnel/
│   ├── 02_cohorts_retention/
│   ├── 03_feature_launch/
│   ├── 04_anomaly_postmortem/
│   └── 05_clinic_deep_dive/
├── model/                feature pipeline, training, model card, MLflow tracking
├── api/                  FastAPI scoring service + tests + Dockerfile
├── dashboard/             Streamlit ops dashboard
├── .github/workflows/    CI: lint, dbt build, analyses, training, API tests
└── Makefile
```

## Running it locally

Requires Python 3.11+.

```bash
git clone <this-repo>
cd msk-pulse
make setup      # install dependencies
make all        # generate data -> build warehouse -> render metrics -> run analyses -> train model -> test
make api        # in one terminal: scoring API on :8000
make dashboard  # in another terminal: dashboard on :8501
```

Or step by step:

```bash
python data_generator/generate.py --out data/raw --seed 42
cd warehouse && dbt build --profiles-dir . && cd ..
cd metrics && python render_dictionary.py && cd ..
cd analyses/01_funnel && python run.py && cd ../..     # repeat for 02-05
cd model && python train.py && cd ..
cd api && pytest tests/ -v && cd ..
```

## Deployment

- **API** — containerized (`api/Dockerfile`) and deployed on Hugging Face Spaces (Docker SDK). Build context is the repo root: `docker build -f api/Dockerfile .`
- **Dashboard** — deployed on Streamlit Community Cloud, pointed at this repo with `dashboard/app.py` as the entrypoint and `SCORING_API_URL` set to the deployed API's URL.
- **Docs** — the metrics dictionary and dbt docs are published via GitHub Pages.

## Data note

Every record in this repository is synthetically generated (`data_generator/generate.py`, seeded for reproducibility). Base approval and utilization rates are loosely calibrated to public CMS/claims statistics, but no real patient, clinic, or payer data is used anywhere in this project. The generator's causal assumptions (which payer/CPT/clinic factors drive approval, retention, and engagement) are documented inline in the generator source and exist specifically so the downstream analyses have real, discoverable patterns to find — including three intentionally planted scenarios: a payer feed data-quality break, a feature launch, and an underperforming clinic.

## License

MIT
