# Verification status (2026-11-11)

- **Unit/API tests:** 7 passed using `python -m pytest -q`.
- **PySpark ingestion:** blocked in this environment. Java 21 is present, but `pyspark` is not installed and pip cannot reach the package index. Existing `serving.db` contains 25 ports, 4,849 shipments, and 24,897 events; these counts are from a previously generated artifact, not a fresh Spark run.
- **Docker Compose:** blocked because the Docker CLI/daemon is not available here.
- **Idempotency:** not verified by two actual Spark executions. The implementation replaces tables, but that is a design property, not an executed proof.
- **Live OpenAI tool calling:** blocked because no `OPENAI_API_KEY` is configured. A mocked `query_shipments` HTTP dispatch passed, but this does not prove a live LLM round trip.
- **Environment:** Python 3.13.5, Java 21.0.12.

To finish on a machine with Docker and internet access, install requirements in a Python 3.11 virtual environment and run `bash scripts/run_full_verification.sh` (with `OPENAI_API_KEY` set to also test the live assistant). The script fails immediately on errors and checks row-count idempotency, which is a necessary but not sufficient idempotency check.
