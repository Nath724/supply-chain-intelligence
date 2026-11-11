"""Spark raw -> curated transformations; SQLite serving layer."""
import argparse
import sqlite3
from pathlib import Path
from pyspark.sql import SparkSession, functions as F, Window


def build(data_dir='data', db='artifacts/serving.db'):
    spark = SparkSession.builder.master('local[2]').appName('supply-chain').config('spark.ui.enabled', 'false').getOrCreate()
    try:
        shipments = spark.read.option('header', True).option('inferSchema', False).csv(str(Path(data_dir) / 'shipments.csv'))
        ports = spark.read.option('header', True).csv(str(Path(data_dir) / 'ports.csv'))
        events = spark.read.option('header', True).csv(str(Path(data_dir) / 'port_events.csv'))
        w = Window.partitionBy('shipment_id').orderBy(F.col('booking_date').asc_nulls_last(), F.col('customer_id').asc_nulls_last(), F.col('vessel_id').asc_nulls_last())
        s = shipments.filter(F.col('shipment_id').isNotNull()).withColumn('rn', F.row_number().over(w)).filter('rn=1').drop('rn')
        valid_ports = ports.select(F.col('port_code').alias('valid_port')).distinct()
        s = s.join(valid_ports, s.origin_port == F.col('valid_port'), 'inner').drop('valid_port')
        s = s.join(valid_ports, s.destination_port == F.col('valid_port'), 'inner').drop('valid_port')
        for c in ('booking_date', 'planned_departure', 'actual_departure', 'planned_arrival', 'actual_arrival'):
            s = s.withColumn(c, F.to_timestamp(c))
        s = s.filter(F.col('planned_arrival') >= F.col('planned_departure'))
        s = s.filter((F.col('container_count').cast('double') > 0) & ((F.col('weight_tons').cast('double') > 0) | F.col('weight_tons').isNull()))
        s = s.filter(F.col('booking_date') <= F.col('planned_departure'))
        s = s.filter(F.col('actual_arrival').isNull() | F.col('actual_departure').isNull() | (F.col('actual_arrival') >= F.col('actual_departure')))
        s = (s.withColumn('container_count', F.col('container_count').cast('int'))
             .withColumn('weight_tons', F.col('weight_tons').cast('double'))
             .withColumn('actual_delay_hours', (F.unix_timestamp('actual_arrival') - F.unix_timestamp('planned_arrival')) / 3600.0)
             .withColumn('on_time_flag', F.when(F.col('actual_delay_hours').isNotNull(), F.col('actual_delay_hours') <= 24))
             .withColumn('route_key', F.concat_ws(' → ', 'origin_port', 'destination_port'))
             .withColumn('transit_days_planned', (F.unix_timestamp('planned_arrival') - F.unix_timestamp('planned_departure')) / 86400.0)
             .withColumn('transit_days_actual', (F.unix_timestamp('actual_arrival') - F.unix_timestamp('actual_departure')) / 86400.0))
        e = events.filter(F.col('event_id').isNotNull()).dropDuplicates(['event_id'])
        e = e.join(valid_ports, e.port_code == F.col('valid_port'), 'inner').drop('valid_port')
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as con:
            # Full replacement makes repeat runs idempotent; suitable for this bounded take-home dataset.
            for name, frame in [('ports', ports), ('shipments', s), ('port_events', e)]:
                frame.toPandas().to_sql(name, con, if_exists='replace', index=False)
            con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_id ON shipments(shipment_id)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_route ON shipments(origin_port, destination_port)')
            con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_events_id ON port_events(event_id)')
    finally:
        spark.stop()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data')
    p.add_argument('--db', default='artifacts/serving.db')
    a = p.parse_args()
    build(a.input, a.db)
