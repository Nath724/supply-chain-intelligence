#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest -q
python -m app.pipeline --input data --db artifacts/serving.db
python - <<'PY'
import sqlite3
with sqlite3.connect('artifacts/serving.db') as con:
 for table in ('ports','shipments','port_events'):
  print(table,con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
PY
python - <<'PY'
import sqlite3,json
with sqlite3.connect('artifacts/serving.db') as con:
 before={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('ports','shipments','port_events')}
open('/tmp/supply_chain_before.json','w').write(json.dumps(before))
PY
python -m app.pipeline --input data --db artifacts/serving.db
python - <<'PY'
import sqlite3,json
with sqlite3.connect('artifacts/serving.db') as con:
 after={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('ports','shipments','port_events')}
before=json.load(open('/tmp/supply_chain_before.json'))
assert before==after,(before,after)
print('IDEMPOTENCY PASS',after)
PY
docker compose up --build -d
trap 'docker compose down' EXIT
python - <<'PY'
import time,urllib.request
for _ in range(40):
 try:
  print(urllib.request.urlopen('http://localhost:8000/health',timeout=2).read().decode());break
 except Exception:time.sleep(3)
else:raise RuntimeError('Docker service health endpoint did not become ready')
PY
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
 python -m app.assistant 'What is the on-time rate for shipments from Shanghai to Rotterdam?'
else
 echo 'LIVE LLM SKIPPED: export OPENAI_API_KEY to run this test'
fi
