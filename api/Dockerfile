# Prior-auth risk API — built for Hugging Face Spaces (Docker SDK).
# HF Spaces expects the container to listen on port 7860.
FROM python:3.11-slim

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY api/ ./
# Trained model artifacts (pipeline, calibrator, metadata) — committed to
# the repo via Git LFS-free small joblib files so the image is self-contained.
COPY model/artifacts/ ./model_artifacts_bundle/
# The loader expects ../model/artifacts relative to api/ — recreate that
# layout inside the image.
RUN mkdir -p /model/artifacts && cp -r /app/model_artifacts_bundle/* /model/artifacts/ \
    && rm -rf /app/model_artifacts_bundle
# clinics.parquet is used to look up each clinic's ops_quality at inference time
COPY data/raw/clinics.parquet /data/raw/clinics.parquet

EXPOSE 7860
ENV PORT=7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
