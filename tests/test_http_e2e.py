"""Real socket-level HTTP smoke test against a subprocess server."""
import socket
import subprocess
import sys
import time

import httpx


def test_real_http_endpoints():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(timeout=3) as client:
            for _ in range(40):
                try:
                    if client.get(base + '/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.25)
            else:
                raise AssertionError('API did not become healthy')
            sid = client.get(base + '/shipments', params={'page_size': 1}).json()['items'][0]['shipment_id']
            assert client.get(base + '/shipments/' + sid).status_code == 200
            assert client.get(base + '/shipments/DOES-NOT-EXIST').status_code == 404
            assert client.get(base + '/data-quality/report').status_code == 200
            assert client.post(base + '/predict-delay', json={'shipment_id': sid}).status_code == 200
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
