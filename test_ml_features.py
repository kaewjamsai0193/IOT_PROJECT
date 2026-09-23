"""Small deterministic tests for timestamp-based ML feature and label creation."""

import pandas as pd

from ml_features import FEATURE_COLUMNS, build_features, build_training_frame


times = pd.date_range("2026-09-16T00:00:00Z", periods=121, freq="10s")
raw = pd.DataFrame(
    {
        "_time": times,
        "car": 4,
        "motorcycle": 1,
        "bus": 0,
        "truck": 0,
        "vehicles_in_roi": range(121),
        "slow_vehicle_ratio": [0.2 if i < 72 else 0.8 for i in range(121)],
        "congestion_level": [0 if i < 72 else 2 for i in range(121)],
    }
)

features = build_features(raw)
assert list(features.columns) == ["_time", *FEATURE_COLUMNS]
assert features.iloc[30]["vehicles_change_5m"] == 29

training = build_training_frame(raw)
row_at_5m = training.loc[training["_time"] == times[30]].iloc[0]
row_at_7m = training.loc[training["_time"] == times[42]].iloc[0]
assert row_at_5m["prediction_for"] == times[60]
assert row_at_5m["target_congestion_level"] == 0
assert row_at_7m["prediction_for"] == times[72]
assert row_at_7m["target_congestion_level"] == 2

print("ML feature tests passed")
