"""Consume live traffic events from Kafka and write five-minute predictions."""

import json
import os
import signal
import sys
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

import joblib
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from kafka import KafkaConsumer

from ml_features import HISTORY_MINUTES, RAW_FEATURE_COLUMNS, build_features


load_dotenv()

STUDENT_ID = os.getenv("STUDENT_ID", "6620301002")
KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS", "172.16.2.117:9092"
).split(",")
KAFKA_INPUT_TOPIC = os.getenv(
    "KAFKA_INPUT_TOPIC", f"traffic-events-{STUDENT_ID}"
)
KAFKA_GROUP_ID = os.getenv(
    "KAFKA_GROUP_ID", f"traffic-ml-predictor-{STUDENT_ID}"
)
INFLUX_URL = os.getenv("INFLUX_URL", "http://172.16.2.117:8086")
INFLUX_ORG = os.getenv("INFLUX_ORG", "my-org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "mini_project")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
PREDICTION_MEASUREMENT = os.getenv(
    "PREDICTION_MEASUREMENT", f"traffic_prediction_{STUDENT_ID}"
)
MODEL_PATH = Path(os.getenv("MODEL_PATH", "model.joblib"))
BUFFER_MINUTES = 10


def load_model_artifact():
  if not MODEL_PATH.exists():
    raise RuntimeError(f"ไม่พบ {MODEL_PATH} กรุณารัน python train_model.py ก่อน")
  artifact = joblib.load(MODEL_PATH)
  required = {"model", "feature_columns", "model_version", "prediction_horizon_minutes"}
  missing = required.difference(artifact)
  if missing:
    raise RuntimeError(f"ไฟล์โมเดลขาดข้อมูล: {', '.join(sorted(missing))}")
  return artifact


def parse_event(value):
  missing = [
      column
      for column in ["timestamp", "camera_id", "student_id", *RAW_FEATURE_COLUMNS]
      if column not in value
  ]
  if missing:
    raise ValueError(f"payload ขาด key: {', '.join(missing)}")
  if str(value["student_id"]) != STUDENT_ID:
    raise ValueError(f"student_id ไม่ตรง: {value['student_id']}")

  event_time = pd.to_datetime(value["timestamp"], utc=True, errors="raise")
  event = {"_time": event_time}
  for column in RAW_FEATURE_COLUMNS:
    event[column] = float(value[column])
  return str(value["camera_id"]), event


def update_buffer(buffer, event):
  buffer.append(event)
  latest = max(item["_time"] for item in buffer)
  cutoff = latest - pd.Timedelta(BUFFER_MINUTES, unit="min")
  ordered = sorted(
      (item for item in buffer if item["_time"] >= cutoff),
      key=lambda item: item["_time"],
  )
  buffer.clear()
  buffer.extend(ordered)


def latest_features(buffer, feature_columns):
  if not buffer:
    return None
  if buffer[-1]["_time"] - buffer[0]["_time"] < pd.Timedelta(
      HISTORY_MINUTES, unit="min"
  ):
    return None
  features = build_features(pd.DataFrame(buffer))
  if features.empty:
    return None
  return features.iloc[-1], features.iloc[-1:][feature_columns]


def prediction_point(camera_id, source_time, artifact, forecast):
  horizon = int(artifact["prediction_horizon_minutes"])
  prediction_for = source_time + timedelta(minutes=horizon)
  forecast = min(3.0, max(0.0, float(forecast)))
  rounded_level = int(forecast + 0.5)
  point = (
      Point(PREDICTION_MEASUREMENT)
      .tag("camera_id", camera_id)
      .tag("student_id", STUDENT_ID)
      .field("forecast_congestion_level", forecast)
      .field("forecast_level_rounded", rounded_level)
      .field("horizon_minutes", horizon)
      .field("model_version", artifact["model_version"])
      .field("prediction_for", prediction_for.isoformat())
      .time(source_time.to_pydatetime(), WritePrecision.S)
  )
  return point, prediction_for, forecast, rounded_level


def main():
  if not INFLUX_TOKEN:
    raise RuntimeError("ไม่พบ INFLUX_TOKEN ใน .env")
  artifact = load_model_artifact()
  if artifact.get("student_id") not in (None, STUDENT_ID):
    raise RuntimeError("student_id ในโมเดลไม่ตรงกับ STUDENT_ID ที่กำลังรัน")

  consumer = KafkaConsumer(
      KAFKA_INPUT_TOPIC,
      bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
      group_id=KAFKA_GROUP_ID,
      auto_offset_reset="latest",
      enable_auto_commit=True,
      value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
  )
  influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
  writer = influx.write_api(write_options=SYNCHRONOUS)
  buffers = defaultdict(lambda: deque(maxlen=500))
  stopping = False

  def stop(_signum, _frame):
    nonlocal stopping
    stopping = True

  signal.signal(signal.SIGINT, stop)
  signal.signal(signal.SIGTERM, stop)

  print(f"อ่าน Kafka topic: {KAFKA_INPUT_TOPIC}")
  print(f"เขียน InfluxDB measurement: {PREDICTION_MEASUREMENT}")
  print(f"ใช้โมเดล: {artifact['model_version']}")
  try:
    while not stopping:
      batches = consumer.poll(timeout_ms=1000, max_records=100)
      for messages in batches.values():
        for message in messages:
          try:
            camera_id, event = parse_event(message.value)
            update_buffer(buffers[camera_id], event)
            result = latest_features(
                buffers[camera_id], artifact["feature_columns"]
            )
            if result is None:
              continue

            feature_row, model_input = result
            forecast = artifact["model"].predict(model_input)[0]
            point, prediction_for, forecast, rounded_level = prediction_point(
                camera_id, feature_row["_time"], artifact, forecast
            )
            writer.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            print(
                f"{camera_id} -> {prediction_for.isoformat()} "
                f"forecast={forecast:.3f} level={rounded_level}",
                flush=True,
            )
          except Exception as error:
            print(
                f"ข้าม Kafka offset {message.offset}: {error}",
                file=sys.stderr,
                flush=True,
            )
  finally:
    consumer.close()
    writer.close()
    influx.close()


if __name__ == "__main__":
  main()
