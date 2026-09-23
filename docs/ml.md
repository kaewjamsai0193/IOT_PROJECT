# สาย ML ทำนายรถติดล่วงหน้า 5 นาที

กลับไปหน้าแรก [README](../README.md)

## โครงสร้างข้อมูลใน InfluxDB

| รายการ | ค่า |
|---|---|
| bucket | `mini_project` (ใช้ร่วมกันทั้งห้อง) |
| measurement | `traffic_6620301002` |
| tags | `camera_id`, `student_id`, `topic` |
| fields | `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`, `slow_vehicle_ratio`, `congestion_level` |

field ทุกตัวเก็บเป็น float เพราะ parser `json` ของ Telegraf แปลงตัวเลขเป็น float ทั้งหมด

bucket นี้ใช้ร่วมกันทั้งห้อง **ทุก query จึงต้องกรองด้วย `student_id` เสมอ**
ไม่งั้นจะได้ข้อมูลของเพื่อนปนมาด้วย

`telegraf.conf` ตั้ง `omit_hostname = true` ไว้ เพราะใน container ค่า `host`
คือ container ID ซึ่งเปลี่ยนทุกครั้งที่สร้าง container ใหม่
ถ้าปล่อยให้ติดไปด้วย InfluxDB จะมองว่าเป็นคนละ series กราฟจะขาดเป็นท่อน

## ML ทำนายรถติดล่วงหน้า 5 นาที

ระบบใช้ time-series regression พยากรณ์ค่า `congestion_level` ในอีก 5 นาที
เป็นตัวเลขต่อเนื่องช่วง `0.0-3.0` แบ่งการทำงานเป็นสองขั้นตอน:

1. `train_model.py` อ่านประวัติจาก InfluxDB สร้าง label ที่เวลาอีก 5 นาที และบันทึก `model.joblib`
2. `predict_consumer.py` อ่านข้อมูลสดจาก Kafka โหลดโมเดล และเขียนผลกลับ InfluxDB

ใช้ข้อมูลจากกล้องสดในการ train ไม่ควรใช้ข้อมูลจากคลิปที่เปิดวนซ้ำ

### 1. Train โมเดล

ติดตั้ง dependency และตรวจว่า `.env` มี `INFLUX_TOKEN` แล้วรัน:

```bash
.venv/bin/python train_model.py
```

ค่าเริ่มต้นอ่านข้อมูลย้อนหลัง 30 วันจาก measurement `traffic_6620301002`
ถ้าข้อมูลน้อยเกินไป หรือค่า `congestion_level` ไม่เปลี่ยนแปลง โปรแกรมจะหยุดพร้อมบอกสาเหตุ
เมื่อสำเร็จจะพิมพ์ MAE, RMSE, R2 และสร้าง `model.joblib`

เปลี่ยนช่วงข้อมูลได้ใน `.env` เช่น:

```dotenv
TRAIN_RANGE=-14d
```

### 2. เปิด Realtime Consumer

```bash
.venv/bin/python predict_consumer.py
```

Consumer อ่าน topic `traffic-events-6620301002` และใช้ consumer group
`traffic-ml-predictor-6620301002` จากนั้นรอสะสมข้อมูลสด 5 นาทีเพื่อสร้าง feature
เมื่อพร้อมแล้วจะเขียน prediction ทุกครั้งที่มี event ใหม่เข้า measurement
`traffic_prediction_6620301002`

จุด prediction ใช้ timestamp ของเวลาที่สร้าง ทำให้ Grafana และ Alert เห็นผลทันที
ส่วนเวลาปลายทางที่พยากรณ์จะอยู่ใน field `prediction_for` เช่นข้อมูลเวลา 08:00
จะมี `prediction_for` เป็น 08:05 มี fields ดังนี้:

| field | ความหมาย |
|---|---|
| `forecast_congestion_level` | ค่าพยากรณ์ต่อเนื่องตั้งแต่ 0.0 ถึง 3.0 |
| `forecast_level_rounded` | ค่าพยากรณ์ที่ปัดเป็นระดับ 0, 1, 2 หรือ 3 |
| `horizon_minutes` | ระยะเวลาที่ทำนายล่วงหน้า ปัจจุบันคือ 5 นาที |
| `model_version` | รุ่นของโมเดลที่ใช้สร้างค่าพยากรณ์ |
| `prediction_for` | เวลาปลายทางของค่าพยากรณ์ |

ดูค่าพยากรณ์บน Grafana ด้วย Flux:

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic_prediction_6620301002")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "forecast_congestion_level")
```

ถ้าต้องการแจ้งเตือน ให้ Grafana Alert แจ้งเมื่อ `forecast_congestion_level >= 1.5`
ต่อเนื่องหลายจุด เพื่อลดการแจ้งเตือนจากค่าที่แกว่งเพียงจุดเดียว
