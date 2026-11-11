"""Run available checks and explicitly report environmental blockers."""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
results = {}
results['pyspark_pipeline'] = {'status':'blocked', 'reason':'pyspark is not installed and package download is unavailable'} if importlib.util.find_spec('pyspark') is None else {'status':'available_to_run'}
results['docker_compose'] = {'status':'blocked', 'reason':'docker executable unavailable'} if not shutil.which('docker') else {'status':'available_to_run'}
results['idempotency'] = {'status':'blocked', 'reason':'cannot execute ingestion twice without PySpark'} if importlib.util.find_spec('pyspark') is None else {'status':'available_to_run'}
results['live_genai'] = {'status':'blocked', 'reason':'OPENAI_API_KEY not configured'} if not os.getenv('OPENAI_API_KEY') else {'status':'available_to_run'}
try:
    import types
    if importlib.util.find_spec("openai") is None:
        sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
    from app.assistant import invoke, ask
    from unittest.mock import MagicMock
    def fake_get(url, params=None):
        r = MagicMock(); r.json.return_value = {'shipments': [{'shipment_id':'SHP-TEST'}]}; return r
    with patch('app.assistant.httpx.Client') as client:
        client.return_value.__enter__.return_value.get.side_effect = fake_get
        result = invoke('query_shipments', {'origin':'CNSHA'})
        assert result['shipments'][0]['shipment_id'] == 'SHP-TEST'
        client.return_value.__enter__.return_value.get.assert_called_once()
    results['genai_tool_dispatch_mock'] = {'status':'passed', 'note':'mocked HTTP tool dispatch, not live LLM'}
except Exception as exc:
    results['genai_tool_dispatch_mock'] = {'status':'failed', 'reason':repr(exc)}
try:
    with sqlite3.connect(ROOT/'artifacts/serving.db') as con:
        names = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {name: con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('ports','shipments','port_events') if name in names}
    results['existing_serving_database'] = {'status':'inspected', 'table_row_counts':counts, 'note':'existing artifact only; not proof of new PySpark execution'}
except Exception as exc:
    results['existing_serving_database'] = {'status':'failed','reason':repr(exc)}
print(json.dumps(results, indent=2))
(ROOT/'artifacts/four_requirements_verification.json').write_text(json.dumps(results,indent=2))
