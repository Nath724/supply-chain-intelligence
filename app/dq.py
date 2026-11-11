"""Independent, repeatable CSV profiling; never mutates raw inputs."""
import argparse
import json
from pathlib import Path
import pandas as pd


def inspect(folder):
    folder = Path(folder)
    frames = {name: pd.read_csv(folder / f'{name}.csv') for name in ('ports', 'shipments', 'port_events')}
    ports, shipments, events = (frames[n] for n in ('ports', 'shipments', 'port_events'))
    checks = []

    def add(table, name, mask, severity, action):
        count = int(mask.fillna(False).sum())
        checks.append(dict(table=table, check=name, rows_affected=count,
                           percentage=round(100 * count / len(frames[table]), 2),
                           severity=severity, recommended_action=action))

    for table, df, key in [('ports', ports, 'port_code'), ('shipments', shipments, 'shipment_id'), ('port_events', events, 'event_id')]:
        add(table, 'duplicate_identifier', df.duplicated(key, keep='first'), 'critical', 'deduplicate deterministically; retain first occurrence')
        add(table, 'missing_identifier', df[key].isna() | df[key].astype(str).str.strip().eq(''), 'critical', 'quarantine')
    for column in ('country', 'region', 'timezone'):
        add('ports', f'missing_{column}', ports[column].isna(), 'warning', 'flag and enrich from reference')
    add('ports', 'invalid_congestion', pd.to_numeric(ports.avg_congestion_score, errors='coerce').isna() | ~pd.to_numeric(ports.avg_congestion_score, errors='coerce').between(0, 1), 'warning', 'flag; exclude from congestion features')
    known = set(ports.port_code)
    for column in ('origin_port', 'destination_port'):
        add('shipments', f'unknown_{column}', ~shipments[column].isin(known), 'critical', 'quarantine shipment')
    add('shipments', 'same_origin_destination', shipments.origin_port.eq(shipments.destination_port), 'warning', 'flag for investigation')
    for column in ('cargo_type', 'weight_tons', 'status'):
        add('shipments', f'missing_{column}', shipments[column].isna(), 'warning', 'preserve null; impute only for model')
    for column in ('container_count', 'weight_tons'):
        values = pd.to_numeric(shipments[column], errors='coerce')
        add('shipments', f'nonpositive_{column}', values.notna() & (values <= 0), 'critical', 'quarantine invalid measure')
    dates = {}
    for column in ('booking_date', 'planned_departure', 'actual_departure', 'planned_arrival', 'actual_arrival'):
        dates[column] = pd.to_datetime(shipments[column], errors='coerce')
        add('shipments', f'invalid_{column}', shipments[column].notna() & dates[column].isna(), 'critical', 'quarantine invalid timestamp')
    add('shipments', 'planned_arrival_before_departure', dates['planned_arrival'] < dates['planned_departure'], 'critical', 'quarantine')
    add('shipments', 'booking_after_planned_departure', dates['booking_date'] > dates['planned_departure'], 'warning', 'flag; exclude from model training')
    add('shipments', 'actual_arrival_before_departure', dates['actual_arrival'] < dates['actual_departure'], 'critical', 'quarantine')
    add('port_events', 'unknown_port', ~events.port_code.isin(known), 'warning', 'quarantine event')
    add('port_events', 'missing_event_type', events.event_type.isna(), 'warning', 'flag')
    add('port_events', 'missing_notes', events.notes.isna(), 'info', 'retain; optional field')
    delay = pd.to_numeric(events.delay_minutes, errors='coerce')
    add('port_events', 'negative_delay_minutes', delay.notna() & (delay < 0), 'warning', 'flag for investigation')
    add('port_events', 'invalid_event_timestamp', pd.to_datetime(events.event_timestamp, errors='coerce').isna(), 'critical', 'quarantine')
    return {'row_counts': {k: len(v) for k, v in frames.items()}, 'checks': checks,
            'notes': 'Checks are not mutually exclusive; totals must not be added.'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data')
    p.add_argument('--output', default='artifacts/dq_report.json')
    args = p.parse_args()
    report = inspect(args.input)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
