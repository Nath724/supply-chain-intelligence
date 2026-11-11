# Interview walkthrough — explain the code

## 1. Problem and design
The platform answers operational shipment queries, validates messy data before ingestion, predicts >24-hour delay risk using booking-time features, and lets an LLM call safe domain tools. PySpark handles ETL; SQLite handles small read-mostly API queries; scikit-learn is the explainable ML baseline.

## 2. File-by-file
- `app/dq.py`: pandas CSV profiling, no DB or Spark dependency; each check returns count, percentage, severity, action. Run before ingestion.
- `app/pipeline.py`: Spark CSV reads, deterministic shipment deduplication, port reference joins, timestamp validation, curated delay/transit calculations, SQLite serving tables. Full-table replacement is idempotent for this take-home scale.
- `app/ml.py`: builds booking-time features, preprocesses categoricals/numerics, trains a class-weighted logistic regression, evaluates held-out metrics and saves joblib.
- `app/api.py`: FastAPI endpoints, SQL parameterization, pagination, route aggregates, model inference, DQ report, JSON errors, request logging.
- `app/assistant.py`: OpenAI function calling, allowlisted tool dispatch to the API, limited tool rounds, structured trace logging.
- `app/bootstrap.py`: runs DQ → ETL → ML on build.
- `tests/`: unit checks, TestClient integration, real HTTP subprocess smoke test.
- `Dockerfile` / `docker-compose.yml`: Java 17 + Python 3.11, build-time artifacts and single-command service.
- `.github/workflows/ci.yml`: lint, bootstrap, tests, image build.

## 3. Walkthrough order
1. Run the DQ module against raw CSVs and inspect `artifacts/dq_report.json`.
2. Explain Spark `route_key`, `actual_delay_hours`, `on_time_flag`, transit calculations and invalid-row policy.
3. Run the API and demo health, pagination, a missing shipment 404, route stats, prediction, and DQ endpoint.
4. Explain why actual timestamps and status are **not** model inputs (target leakage).
5. Show metrics; AUC around 0.506 is near random and should not be oversold.
6. Explain that the assistant chooses tools, while the API owns data access and ML inference.
7. Show tests, CI, Docker and the production support runbook.

## 4. Limitations to acknowledge
- Spark and Docker were not executable in the preparation environment; validate the full clean build locally before submitting.
- The included model artifact was trained with a pandas reconstruction of the curated transformations, not the Spark execution path; the Docker bootstrap trains via Spark.
- The baseline split is random, not temporal, so temporal generalization remains unknown.
- Events have no shipment ID and cannot be attributed to specific shipments reliably.
- No auth, managed secret store, incremental ingestion, or production alerting.
- Static congestion scores may not reflect historical booking-time conditions; verify source freshness in production.

## 5. Useful interview questions
**Why Spark for small CSVs?** It demonstrates a future distributed processing path; pandas is faster for the standalone DQ step at this volume.

**Why SQLite?** Tiny deployment footprint, indexed reads, and simple reproducibility; migrate to PostgreSQL/Parquet as volume and concurrency grow.

**How is the pipeline idempotent?** Deterministic deduplication and complete replacement of serving tables. For production, switch to incremental upserts and durable checkpoints.

**How are unknown ports handled?** The DQ report flags them; the curated shipment layer drops rows without valid origin/destination references.

**Why is the AUC low?** Booking-time features contain limited signal in the supplied data; reporting the limitation is more trustworthy than tuning on test data.

**What does the GenAI guardrail do?** The assistant is domain-restricted, cannot execute arbitrary SQL, has a fixed allowlist and a four-round cap, and must attribute claims to tools.
