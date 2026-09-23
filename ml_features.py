"""Feature engineering shared by offline training and realtime prediction."""

import math

import pandas as pd


RAW_FEATURE_COLUMNS = [
    "car",
    "motorcycle",
    "bus",
    "truck",
    "vehicles_in_roi",
    "slow_vehicle_ratio",
    "congestion_level",
]

FEATURE_COLUMNS = RAW_FEATURE_COLUMNS + [
    "vehicles_mean_1m",
    "vehicles_mean_5m",
    "vehicles_max_5m",
    "vehicles_change_5m",
    "slow_mean_1m",
    "slow_mean_5m",
    "slow_max_5m",
    "slow_change_5m",
    "level_mean_5m",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
]

HISTORY_MINUTES = 5
PREDICTION_HORIZON_MINUTES = 5


def prepare_raw_frame(frame):
  """Validate and normalize raw traffic records into a UTC time-indexed frame."""
  frame = frame.copy()
  if "_time" not in frame and "timestamp" in frame:
    frame = frame.rename(columns={"timestamp": "_time"})

  missing = [c for c in ["_time", *RAW_FEATURE_COLUMNS] if c not in frame]
  if missing:
    raise ValueError(f"ข้อมูลขาดคอลัมน์: {', '.join(missing)}")

  frame["_time"] = pd.to_datetime(frame["_time"], utc=True, errors="coerce")
  for column in RAW_FEATURE_COLUMNS:
    frame[column] = pd.to_numeric(frame[column], errors="coerce")

  return (
      frame.dropna(subset=["_time", *RAW_FEATURE_COLUMNS])
      .sort_values("_time")
      .drop_duplicates("_time", keep="last")
      .set_index("_time")
  )


def build_features(raw_frame):
  """Build one feature row per event using only data available at that event."""
  raw = prepare_raw_frame(raw_frame)
  if raw.empty:
    return pd.DataFrame(columns=["_time", *FEATURE_COLUMNS])

  features = raw[RAW_FEATURE_COLUMNS].copy()
  vehicles = raw["vehicles_in_roi"]
  slow = raw["slow_vehicle_ratio"]

  features["vehicles_mean_1m"] = vehicles.rolling("1min", min_periods=1).mean()
  features["vehicles_mean_5m"] = vehicles.rolling("5min", min_periods=1).mean()
  features["vehicles_max_5m"] = vehicles.rolling("5min", min_periods=1).max()
  features["vehicles_change_5m"] = vehicles.rolling(
      "5min", min_periods=1
  ).apply(lambda values: values[-1] - values[0], raw=True)

  features["slow_mean_1m"] = slow.rolling("1min", min_periods=1).mean()
  features["slow_mean_5m"] = slow.rolling("5min", min_periods=1).mean()
  features["slow_max_5m"] = slow.rolling("5min", min_periods=1).max()
  features["slow_change_5m"] = slow.rolling("5min", min_periods=1).apply(
      lambda values: values[-1] - values[0], raw=True
  )
  features["level_mean_5m"] = raw["congestion_level"].rolling(
      "5min", min_periods=1
  ).mean()

  local_time = features.index.tz_convert("Asia/Bangkok")
  hour = local_time.hour + local_time.minute / 60.0
  weekday = local_time.dayofweek
  features["hour_sin"] = [math.sin(2 * math.pi * h / 24) for h in hour]
  features["hour_cos"] = [math.cos(2 * math.pi * h / 24) for h in hour]
  features["weekday_sin"] = [math.sin(2 * math.pi * d / 7) for d in weekday]
  features["weekday_cos"] = [math.cos(2 * math.pi * d / 7) for d in weekday]

  return features.reset_index()[["_time", *FEATURE_COLUMNS]]


def build_training_frame(raw_frame):
  """Attach the congestion level observed closest to five minutes in the future."""
  raw = prepare_raw_frame(raw_frame)
  features = build_features(raw.reset_index())
  if features.empty:
    return features.assign(target_congestion_level=pd.Series(dtype="float64"))

  # Remove rows whose rolling history is shorter than the realtime warm-up period.
  first_ready = raw.index.min() + pd.Timedelta(HISTORY_MINUTES, unit="min")
  features = features.loc[features["_time"] >= first_ready].copy()
  features["prediction_for"] = features["_time"] + pd.Timedelta(
      PREDICTION_HORIZON_MINUTES, unit="min"
  )

  targets = (
      raw[["congestion_level"]]
      .reset_index()
      .rename(
          columns={
              "_time": "target_time",
              "congestion_level": "target_congestion_level",
          }
      )
  )
  training = pd.merge_asof(
      features.sort_values("prediction_for"),
      targets.sort_values("target_time"),
      left_on="prediction_for",
      right_on="target_time",
      direction="nearest",
      tolerance=pd.Timedelta(30, unit="s"),
  )
  return training.dropna(subset=["target_congestion_level"])
