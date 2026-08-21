# Deploying MSK Pulse

Two pieces to deploy: the scoring API (Hugging Face Spaces) and the dashboard (Streamlit Community Cloud). Do them in this order — the dashboard needs the API's URL.

## 1. Push to GitHub

```bash
cd msk-pulse
git init
git add .
git commit -m "Initial commit: MSK Pulse"
git branch -M main
git remote add origin https://github.com/<your-username>/msk-pulse.git
git push -u origin main
```

If `data/raw/` and `model/artifacts/*.joblib` are gitignored in your setup, first run `make all` locally (see README) so those files exist, then `git add -f data/raw/*.parquet model/artifacts/*.joblib model/artifacts/metadata.json` before committing — the API Docker build and the dashboard both need them.

## 2. Deploy the API to Hugging Face Spaces

1. Go to huggingface.co → New Space.
2. Name it (e.g. `msk-pulse-api`), pick **Docker** as the Space SDK, set visibility to Public.
3. Once created, either:
   - **Link to GitHub:** in the Space's Settings → Repository, connect it to your `msk-pulse` GitHub repo. Set the Dockerfile path to `api/Dockerfile` and build context to the repo root.
   - **Or push directly:** `git remote add space https://huggingface.co/spaces/<your-username>/msk-pulse-api` then `git push space main`. HF Spaces auto-detects `api/Dockerfile` when it's at that path, or you may need to copy `api/Dockerfile` to the Space repo root as `Dockerfile`.
4. Wait for the build (a few minutes). Your API will be live at `https://<your-username>-msk-pulse-api.hf.space`.
5. Verify: `curl https://<your-username>-msk-pulse-api.hf.space/health` should return `{"status":"ok"}`.

## 3. Deploy the dashboard to Streamlit Community Cloud

1. Go to share.streamlit.io → New app.
2. Point it at your `msk-pulse` GitHub repo, branch `main`, main file path `dashboard/app.py`.
3. Under **Advanced settings → Secrets**, add:
   ```toml
   SCORING_API_URL = "https://<your-username>-msk-pulse-api.hf.space"
   ```
4. Deploy. The dashboard also needs `warehouse/msk_pulse.duckdb` to exist in the repo (dbt build output) — either commit it (small enough for a demo dataset) or add a `packages.txt`/startup step that runs `dbt build` on Streamlit Cloud's container before the app starts. Simplest for a portfolio deploy: commit `warehouse/msk_pulse.duckdb` directly (`git add -f warehouse/msk_pulse.duckdb`).

## 4. Docs site (optional but recommended)

```bash
cd warehouse && dbt docs generate --profiles-dir .
```

Publish `warehouse/target/index.html` (and the accompanying assets) plus `metrics/METRICS_DICTIONARY.md` via GitHub Pages (Settings → Pages → deploy from a `docs/` folder or the `gh-pages` branch).

## Checklist before sharing the links

- [ ] `GET /health` on the API returns 200
- [ ] `POST /score` on the API returns a prediction for a sample payload (see `api/tests/test_api.py` for one)
- [ ] Dashboard loads all four pages without error
- [ ] Dashboard's "Prior-auth risk screen" page successfully calls the live API (not localhost)
- [ ] README links at the top point to the real deployed URLs, not placeholders
