from fastapi.testclient import TestClient
from app.api import app

client = TestClient(app)


def test_health():
    assert client.get('/health').status_code == 200


def test_lookup_and_missing():
    rows = client.get('/shipments', params={'page_size': 1}).json()['items']
    assert rows
    assert client.get('/shipments/' + rows[0]['shipment_id']).status_code == 200
    assert client.get('/shipments/UNKNOWN-ID').status_code == 404


def test_quality_report():
    assert 'checks' in client.get('/data-quality/report').json()


def test_prediction():
    sid = client.get('/shipments', params={'page_size': 1}).json()['items'][0]['shipment_id']
    result = client.post('/predict-delay', json={'shipment_id': sid})
    assert result.status_code == 200, result.text
    assert 0 <= result.json()['delay_risk_probability'] <= 1
