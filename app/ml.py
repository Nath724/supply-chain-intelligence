"""Leakage-safe booking-time features and held-out evaluation."""
import argparse
import json
import sqlite3
from pathlib import Path
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL = ['origin_port', 'destination_port', 'cargo_type']
NUMERIC = ['container_count', 'weight_tons', 'planned_transit_days', 'booking_month', 'origin_congestion', 'destination_congestion']


def features(df, ports):
    x = df.copy()
    x['planned_transit_days'] = (pd.to_datetime(x.planned_arrival) - pd.to_datetime(x.planned_departure)).dt.total_seconds() / 86400
    x['booking_month'] = pd.to_datetime(x.booking_date).dt.month
    congestion = ports.set_index('port_code')['avg_congestion_score'].to_dict()
    x['origin_congestion'] = x.origin_port.map(congestion)
    x['destination_congestion'] = x.destination_port.map(congestion)
    for c in NUMERIC:
        x[c] = pd.to_numeric(x[c], errors='coerce')
    return x[CATEGORICAL + NUMERIC]


def train(db='artifacts/serving.db', output='artifacts/model.joblib'):
    with sqlite3.connect(db) as con:
        shipments = pd.read_sql_query('SELECT * FROM shipments WHERE actual_delay_hours IS NOT NULL', con)
        ports = pd.read_sql_query('SELECT * FROM ports', con)
    x = features(shipments, ports)
    y = (shipments.actual_delay_hours > 24).astype(int)
    if y.nunique() < 2:
        raise ValueError('Need both target classes to train')
    xtrain, xtest, ytrain, ytest = train_test_split(x, y, test_size=0.25, random_state=42, stratify=y)
    prep = ColumnTransformer([
        ('categorical', Pipeline([('impute', SimpleImputer(strategy='constant', fill_value='Unknown')),
                                  ('onehot', OneHotEncoder(handle_unknown='ignore'))]), CATEGORICAL),
        ('numeric', Pipeline([('impute', SimpleImputer(strategy='median')),
                              ('scale', StandardScaler())]), NUMERIC)])
    model = Pipeline([('preprocess', prep), ('classifier', LogisticRegression(max_iter=1000, class_weight='balanced'))])
    model.fit(xtrain, ytrain)
    probs = model.predict_proba(xtest)[:, 1]
    predictions = (probs >= 0.5).astype(int)
    metrics = {'test_rows': len(ytest), 'positive_rate': float(ytest.mean()),
               'precision': float(precision_score(ytest, predictions, zero_division=0)),
               'recall': float(recall_score(ytest, predictions, zero_division=0)),
               'f1': float(f1_score(ytest, predictions, zero_division=0)),
               'auc': float(roc_auc_score(ytest, probs))}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output)
    Path(output).with_name('metrics.json').write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='artifacts/serving.db')
    p.add_argument('--output', default='artifacts/model.joblib')
    a = p.parse_args()
    print(json.dumps(train(a.db, a.output), indent=2))
