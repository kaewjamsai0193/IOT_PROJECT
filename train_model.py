"""Train the five-minute traffic congestion model from InfluxDB history."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import make_pipeline

from ml_features import (
    FEATURE_COLUMNS,
    PREDICTION_HORIZON_MINUTES,
    RAW_FEATURE_COLUMNS,
    build_training_frame,
)


load_dotenv()

INFLUX_URL = os.getenv("INFLUX_URL", "http://172.16.2.117:8086")
INFLUX_ORG = os.getenv("INFLUX_ORG", "my-org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "mini_project")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
STUDENT_ID = os.getenv("STUDENT_ID", "6620301002")
SOURCE_MEASUREMENT = os.getenv("SOURCE_MEASUREMENT", f"traffic_{STUDENT_ID}")
TRAIN_RANGE = os.getenv("TRAIN_RANGE", "-30d")
MODEL_PATH = Path(os.getenv("MODEL_PATH", "model.joblib"))


def flux_string(value):
  return json.dumps(value)


def load_history():
  if not INFLUX_TOKEN:
    raise RuntimeError("ไม่พบ INFLUX_TOKEN ใน .env")

  field_names = ", ".join(flux_string(name) for name in RAW_FEATURE_COLUMNS)
  query = f'''
from(bucket: {flux_string(INFLUX_BUCKET)})
  |> range(start: {TRAIN_RANGE})
  |> filter(fn: (r) => r._measurement == {flux_string(SOURCE_MEASUREMENT)})
  |> filter(fn: (r) => r.student_id == {flux_string(STUDENT_ID)})
  |> filter(fn: (r) => contains(value: r._field, set: [{field_names}]))
  |> keep(columns: ["_time", "_field", "_value"])
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''

  with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
    result = client.query_api().query_data_frame(query)

  frames = result if isinstance(result, list) else [result]
  frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
  if not frames:
    raise RuntimeError("ไม่พบข้อมูลย้อนหลังใน InfluxDB ตาม measurement และช่วงเวลาที่กำหนด")
  return pd.concat(frames, ignore_index=True)


def train(history):
  dataset = build_training_frame(history)
  if len(dataset) < 100:
    raise RuntimeError(
        f"ข้อมูลที่จับคู่เป้าหมายได้มีเพียง {len(dataset)} แถว ต้องมีอย่างน้อย 100 แถว"
    )
  if dataset["target_congestion_level"].nunique() < 2:
    raise RuntimeError("congestion_level ในข้อมูลไม่เปลี่ยนแปลง จึงยัง train regression ไม่ได้")

  split = int(len(dataset) * 0.8)
  train_set, test_set = dataset.iloc[:split], dataset.iloc[split:]
  if train_set["target_congestion_level"].nunique() < 2:
    raise RuntimeError("congestion_level ในช่วง train ไม่เปลี่ยนแปลง กรุณาเพิ่มข้อมูลย้อนหลัง")

  model = make_pipeline(
      SimpleImputer(strategy="median"),
      RandomForestRegressor(
          n_estimators=300,
          min_samples_leaf=5,
          random_state=42,
          n_jobs=-1,
      ),
  )
  model.fit(train_set[FEATURE_COLUMNS], train_set["target_congestion_level"])

  actual = test_set["target_congestion_level"]
  predicted = model.predict(test_set[FEATURE_COLUMNS]).clip(0.0, 3.0)
  print(f"ข้อมูลทั้งหมด {len(dataset)} แถว (train={len(train_set)}, test={len(test_set)})")
  print(f"MAE:  {mean_absolute_error(actual, predicted):.3f}")
  print(f"RMSE: {root_mean_squared_error(actual, predicted):.3f}")
  print(f"R2:   {r2_score(actual, predicted):.3f}")

  trained_at_time = datetime.now(timezone.utc)
  trained_at = trained_at_time.isoformat(timespec="seconds")
  artifact = {
      "model": model,
      "feature_columns": FEATURE_COLUMNS,
      "trained_at": trained_at,
      "model_version": trained_at_time.strftime("%Y%m%dT%H%M%SZ"),
      "student_id": STUDENT_ID,
      "source_measurement": SOURCE_MEASUREMENT,
      "prediction_horizon_minutes": PREDICTION_HORIZON_MINUTES,
      "target": "congestion_level",
      "task": "regression_forecast",
  }
  MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
  joblib.dump(artifact, MODEL_PATH)
  print(f"บันทึกโมเดลแล้ว: {MODEL_PATH}")


if __name__ == "__main__":
  train(load_history())
