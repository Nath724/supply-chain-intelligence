"""Repeatable local verification and lightweight HTTP performance smoke benchmark."""
import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import app


def main():
    start = time.perf_counter()
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    with TestClient(app) as client:
        endpoints = [('/health', 'get'), ('/shipments?page_size=10', 'get'),
                     ('/shipments/SHP-00421', 'get'), ('/data-quality/report', 'get'),
                     ('/predict-delay', 'post')]
        report = {}
        for path, method in endpoints:
            durations = []
            for _ in range(30):
                t = time.perf_counter()
                response = client.post(path, json={'shipment_id': 'SHP-00421'}) if method == 'post' else client.get(path)
                durations.append((time.perf_counter() - t) * 1000)
                if response.status_code != 200:
                    raise RuntimeError(f'{path}: {response.status_code} {response.text}')
            durations.sort()
            report[path] = {'requests': len(durations), 'median_ms': round(durations[14], 2),
                            'p95_ms': round(durations[28], 2), 'max_ms': round(durations[-1], 2)}
    result_data = {'test_status': 'passed', 'test_runtime_s': round(time.perf_counter()-start, 2),
                   'benchmark_type': 'in-process FastAPI TestClient; not production load testing',
                   'endpoints': report, 'spark_pipeline_verified': False, 'docker_verified': False}
    path = Path('artifacts/verification.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result_data, indent=2) + '\n')
    print(json.dumps(result_data, indent=2))


if __name__ == '__main__':
    main()
