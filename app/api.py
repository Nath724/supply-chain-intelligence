import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .ml import features

DB = os.getenv('DB_PATH', 'artifacts/serving.db')
MODEL = os.getenv('MODEL_PATH', 'artifacts/model.joblib')
REPORT = os.getenv('DQ_PATH', 'artifacts/dq_report.json')
logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('api')
app = FastAPI(title='Supply Chain Intelligence', version='1.0.0')


@contextmanager
def connect():
    if not Path(DB).exists():
        raise HTTPException(503, 'Serving database not initialized')
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def shipment(shipment_id):
    with connect() as con:
        row = con.execute('SELECT * FROM shipments WHERE shipment_id=?', (shipment_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Shipment not found')
    return dict(row)


@app.middleware('http')
async def log_request(request: Request, call_next):
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        log.exception(json.dumps({'event': 'unhandled_exception', 'request_id': request_id}))
        response = JSONResponse(status_code=500, content={'error': {'code': 500, 'message': 'Internal server error'}})
    response.headers['X-Request-ID'] = request_id
    log.info(json.dumps({'event': 'http_request', 'request_id': request_id, 'method': request.method,
                         'path': request.url.path, 'status': response.status_code,
                         'latency_ms': round((time.perf_counter()-start)*1000, 2)}))
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={'error': {'code': exc.status_code, 'message': exc.detail}})


@app.get('/health')
def health():
    ready = Path(DB).exists() and Path(MODEL).exists() and Path(REPORT).exists()
    return JSONResponse(status_code=200 if ready else 503,
                        content={'status': 'ok' if ready else 'not_ready', 'version': '1.0.0'})


@app.get('/shipments/{shipment_id}')
def get_shipment(shipment_id: str):
    return shipment(shipment_id)


@app.get('/shipments')
def list_shipments(origin: str | None = None, destination: str | None = None,
                   status: str | None = None, start_date: str | None = None, end_date: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    conditions, args = [], []
    for column, value in [('origin_port', origin), ('destination_port', destination), ('status', status)]:
        if value:
            conditions.append(f'{column}=?')
            args.append(value)
    for op, date in [('>=', start_date), ('<=', end_date)]:
        if date:
            try:
                pd.to_datetime(date, format='%Y-%m-%d', errors='raise')
            except (ValueError, TypeError):
                raise HTTPException(422, 'Dates must be YYYY-MM-DD')
            conditions.append(f'date(booking_date){op}date(?)')
            args.append(date)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    with connect() as con:
        count = con.execute('SELECT COUNT(*) FROM shipments' + where, args).fetchone()[0]
        rows = con.execute('SELECT * FROM shipments' + where + ' ORDER BY shipment_id LIMIT ? OFFSET ?',
                           [*args, page_size, (page-1)*page_size]).fetchall()
    return {'items': [dict(r) for r in rows], 'total': count, 'page': page, 'page_size': page_size}


@app.get('/routes/{origin}/{destination}/stats')
def route_stats(origin: str, destination: str):
    with connect() as con:
        row = con.execute('''SELECT COUNT(*) AS shipment_count, AVG(actual_delay_hours) AS average_delay_hours,
            AVG(CASE WHEN actual_delay_hours IS NOT NULL THEN on_time_flag END) AS on_time_rate,
            COUNT(actual_delay_hours) AS completed_count FROM shipments
            WHERE origin_port=? AND destination_port=?''', (origin, destination)).fetchone()
    if row['shipment_count'] == 0:
        raise HTTPException(404, 'Route not found')
    return {'origin': origin, 'destination': destination, **dict(row)}


class PredictionRequest(BaseModel):
    shipment_id: str | None = None
    origin_port: str | None = None
    destination_port: str | None = None
    cargo_type: str | None = None
    container_count: int | None = None
    weight_tons: float | None = None
    booking_date: str | None = None
    planned_departure: str | None = None
    planned_arrival: str | None = None


@lru_cache(maxsize=1)
def loaded_model():
    return joblib.load(MODEL)


@app.post('/predict-delay')
def predict_delay(body: PredictionRequest):
    if not Path(MODEL).exists():
        raise HTTPException(503, 'Model artifact missing')
    if body.shipment_id:
        data = shipment(body.shipment_id)
    else:
        data = body.model_dump(exclude_none=True)
        required = ['origin_port', 'destination_port', 'booking_date', 'planned_departure', 'planned_arrival']
        if any(not data.get(k) for k in required):
            raise HTTPException(422, f'Required fields: {required}')
    with connect() as con:
        ports = pd.read_sql_query('SELECT port_code, avg_congestion_score FROM ports', con)
    try:
        x = features(pd.DataFrame([data]), ports)
        if x.planned_transit_days.isna().any() or x.booking_month.isna().any():
            raise ValueError('Invalid dates')
        probability = float(loaded_model().predict_proba(x)[0, 1])
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'shipment_id': body.shipment_id, 'delay_risk_probability': probability,
            'high_risk': probability >= 0.5, 'threshold_hours': 24, 'decision_threshold': 0.5}


@app.get('/data-quality/report')
def quality_report():
    if not Path(REPORT).exists():
        raise HTTPException(503, 'Quality report missing')
    return json.loads(Path(REPORT).read_text())
