import pandas as pd
from app.ml import features
from app.dq import inspect


def test_booking_features_do_not_leak_actuals():
    shipment = pd.DataFrame([{'origin_port': 'A', 'destination_port': 'B', 'cargo_type': 'Food',
      'booking_date': '2024-01-01', 'planned_departure': '2024-01-02', 'planned_arrival': '2024-01-04',
      'actual_arrival': '2024-02-01', 'container_count': 2, 'weight_tons': 10}])
    ports = pd.DataFrame([{'port_code': 'A', 'avg_congestion_score': 0.2}, {'port_code': 'B', 'avg_congestion_score': 0.5}])
    x = features(shipment, ports)
    assert 'actual_arrival' not in x.columns
    assert x.planned_transit_days.iloc[0] == 2


def test_dq_is_repeatable():
    assert inspect('data') == inspect('data')
    assert any(c['rows_affected'] > 0 for c in inspect('data')['checks'])
