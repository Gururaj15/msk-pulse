.PHONY: setup data build metrics analyze train api dashboard test lint all clean

setup:
	pip install -r requirements.txt

data:
	python data_generator/generate.py --out data/raw --seed 42

build:
	cd warehouse && dbt build --profiles-dir .

metrics:
	cd metrics && python render_dictionary.py

analyze:
	for d in 01_funnel 02_cohorts_retention 03_feature_launch 04_anomaly_postmortem 05_clinic_deep_dive; do \
		echo "--- analyses/$$d ---"; \
		(cd analyses/$$d && python run.py) || exit 1; \
	done

train:
	cd model && python train.py

api:
	cd api && uvicorn main:app --reload --port 8000

dashboard:
	cd dashboard && streamlit run app.py

test:
	cd api && pytest tests/ -v

lint:
	ruff check .

# Full pipeline, in dependency order: data -> warehouse -> metrics ->
# analyses -> model. Run this once after cloning, before `make api` /
# `make dashboard`.
all: data build metrics analyze train test
	@echo "\nPipeline complete. Run 'make api' and, in another terminal, 'make dashboard'."

clean:
	rm -rf data/raw/*.parquet data/raw/*.json warehouse/*.duckdb warehouse/target
	rm -rf model/artifacts/*
	find . -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
