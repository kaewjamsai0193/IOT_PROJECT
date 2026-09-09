# IOT_PROJECT — ตรวจจับสภาพจราจรจากวิดีโอ

ตรวจจับสภาพจราจรด้วย YOLO + ByteTrack แล้วส่งผลขึ้น MQTT
จากนั้น Telegraf กระจายข้อมูลออกสองทาง คือเข้า InfluxDB เพื่อดูบน Grafana
และเข้า Kafka เพื่อให้โมเดล ML ทำนายรถติดล่วงหน้า (ส่วนหลังยังไม่ได้ทำ)

```
testmqtt.py (YOLO + ByteTrack)  ──── JSON ────▶  Mosquitto (:1883)
                                                  topic: traffic/6620301002
                                                        │
                                                        ▼
                                                   Telegraf
                              ┌─────────────────────────┴─────────────────────────┐
                              ▼                                                   ▼
              InfluxDB 172.16.2.117:8086                            Kafka (:9092)
              bucket: mini_project ──▶ Grafana                      topic: traffic-events
```

## ติดตั้ง

```bash
pip install ultralytics opencv-python numpy paho-mqtt torch
```

น้ำหนักโมเดล (`*.pt`) ไม่ได้อยู่ใน repo เพราะไฟล์ใหญ่ ultralytics โหลดให้เองตอนรันครั้งแรก

ตั้ง token ของ InfluxDB

```bash
cp .env.example .env
# แก้ .env แล้วใส่ token ที่อาจารย์แจก
```

`.env` ถูก gitignore ไว้แล้ว **ห้าม commit ขึ้น repo เพราะ repo นี้เป็น public**

## ใช้งาน

```bash
docker compose up -d          # Mosquitto, Kafka, Telegraf
python testmqtt.py test.mov   # q หรือ ESC = ออก, space = หยุดชั่วคราว
```

รันโดยไม่เปิดหน้าต่างแสดงผล

```bash
python testmqtt.py test.mov --no-show
```

รับภาพจากกล้องจริงหรือ RTSP

```bash
python testmqtt.py 0
python testmqtt.py rtsp://192.168.1.50/stream
```

ถ้าแก้ `telegraf.conf` ต้องสั่งรีสตาร์ตเอง `docker compose up -d` ไม่พอ
เพราะไฟล์ถูก mount เป็น volume ไม่ใช่ส่วนหนึ่งของสเปค container

```bash
docker compose restart telegraf
```

### อาร์กิวเมนต์

| อาร์กิวเมนต์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `video` | `test.mov` | ไฟล์วิดีโอ, RTSP URL, หรือเลขกล้อง (`0` = webcam) |
| `--model` | `yolo26s.pt` | น้ำหนักโมเดล YOLO |
| `--roi` | `mapreal.png` | ภาพที่วาดขอบเขตถนนด้วยเส้นสีแดง (ใส่ `none` เพื่อตรวจทั้งเฟรม) |
| `--no-show` | – | ไม่เปิดหน้าต่างแสดงผล |

## payload ที่ส่งขึ้น MQTT

ส่งไปที่ topic `traffic/6620301002`

```json
{
  "timestamp": "2026-09-09T14:41:27+07:00",
  "camera_id": "CAM_BUILDING2_FL02",
  "student_id": "6620301002",
  "car": 6,
  "motorcycle": 0,
  "bus": 0,
  "truck": 0,
  "vehicles_in_roi": 6,
  "slow_vehicle_ratio": 0.0,
  "congestion_level": 0
}
```

`congestion_level` คือ 0 = FREE, 1 = MODERATE, 2 = HEAVY, 3 = JAM
ค่านี้เป็นตัวเลขเสมอ ไม่มี null แม้ตอนที่ไม่มีรถใน ROI เลย (ถนนว่างคือถนนที่ไม่ติด)

### เรื่องความถี่ในการส่ง

`INTERVAL_SEC = 10` แต่ความหมายต่างกันตามชนิดของแหล่งภาพ

| แหล่งภาพ | ระยะห่างจริง |
|---|---|
| กล้องสด, RTSP, webcam | ทุก 10 วินาทีจริง |
| ไฟล์วิดีโอ แบบเปิดหน้าต่าง | ทุก 10 วินาทีจริง |
| ไฟล์วิดีโอ แบบ `--no-show` | เร็วกว่า 10 วินาที |

ตอนอ่านจากไฟล์ โค้ดนับรอบส่งจากจำนวนเฟรม คือ 10 วินาที**ของเวลาในวิดีโอ**
ซึ่งจะเท่ากับ 10 วินาทีจริงก็ต่อเมื่อวิดีโอเล่นด้วยความเร็วปกติ

การหน่วงให้เล่นตามเวลาจริงอยู่ในบล็อก `if show:` เท่านั้น ดังนั้น

- เปิดหน้าต่างแสดงผล วิดีโอเล่นความเร็วปกติ ได้ 10 วินาทีจริงตามที่ควรเป็น
- ใส่ `--no-show` ไม่มีการหน่วง ประมวลผลเร็วสุดที่เครื่องทำได้
  บน Mac ที่ใช้ MPS วัดได้ราว 5 วินาทีต่อจุด

ถ้าต้องการข้อมูลที่ระยะห่างสม่ำเสมอไปเทรนโมเดล ให้รันแบบเปิดหน้าต่าง
หรือใช้กล้องสด อย่าใช้ `--no-show` กับไฟล์วิดีโอ

## โครงสร้างข้อมูลใน InfluxDB

| รายการ | ค่า |
|---|---|
| bucket | `mini_project` (ใช้ร่วมกันทั้งห้อง) |
| measurement | `traffic` |
| tags | `camera_id`, `student_id`, `topic` |
| fields | `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`, `slow_vehicle_ratio`, `congestion_level` |

field ทุกตัวเก็บเป็น float เพราะ parser `json` ของ Telegraf แปลงตัวเลขเป็น float ทั้งหมด

bucket นี้ใช้ร่วมกันทั้งห้อง **ทุก query จึงต้องกรองด้วย `student_id` เสมอ**
ไม่งั้นจะได้ข้อมูลของเพื่อนปนมาด้วย

`telegraf.conf` ตั้ง `omit_hostname = true` ไว้ เพราะใน container ค่า `host`
คือ container ID ซึ่งเปลี่ยนทุกครั้งที่สร้าง container ใหม่
ถ้าปล่อยให้ติดไปด้วย InfluxDB จะมองว่าเป็นคนละ series กราฟจะขาดเป็นท่อน

## Dashboard บน Grafana

สร้าง panel แล้วเลือก datasource เป็น InfluxDB ที่ชี้ไป bucket `mini_project`
จากนั้นคัดลอก query ข้างล่างไปวาง

### Panel 1 — สถานะปัจจุบัน (Stat)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "congestion_level")
  |> last()
```

ตั้ง Value mappings ให้ `0` → `FREE` เขียว, `1` → `MODERATE` เหลือง,
`2` → `HEAVY` ส้ม, `3` → `JAM` แดง

อยากโชว์จำนวนรถคู่กัน ให้เพิ่ม query ที่สองในหน้าเดียวกัน
โดยเปลี่ยน `congestion_level` เป็น `vehicles_in_roi`

### Panel 2 — จำนวนรถแยกประเภทตามเวลา (Time series)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => contains(value: r._field, set: ["car", "motorcycle", "bus", "truck"]))
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

ตั้ง Graph styles เป็น Stacked เพื่อให้เห็นสัดส่วนของแต่ละประเภท

### Panel 3 — ไทม์ไลน์ระดับความติดขัด (State timeline)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "congestion_level")
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
```

ใช้ Value mappings ชุดเดียวกับ Panel 1

## ตรวจว่าข้อมูลถึง InfluxDB จริง

```bash
set -a && . ./.env && set +a
curl -s -XPOST "http://172.16.2.117:8086/api/v2/query?org=my-org" \
  -H "Authorization: Token $INFLUX_TOKEN" \
  -H "Content-Type: application/vnd.flux" \
  -H "Accept: application/csv" \
  -d 'from(bucket:"mini_project")
      |> range(start: -30m)
      |> filter(fn: (r) => r._measurement == "traffic" and r.student_id == "6620301002")
      |> last()'
```

## ทดสอบ

```bash
python3 test_payload.py
```

สคริปต์ assert ธรรมดา ไม่ต้องลง pytest ตรวจสองเรื่องที่ปลายทางพึ่งอยู่
คือ `congestion_level` ต้องไม่เป็น null และทุก payload ต้องมี `student_id`

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `testmqtt.py` | ตรวจจับ ติดตาม ตัดสินสภาพจราจร แล้วส่ง payload ขึ้น MQTT |
| `test_payload.py` | ตรวจว่า payload ถูกต้อง |
| `mapreal.png` | ภาพ ROI ที่วาดขอบเขตถนนด้วยเส้นสีแดง |
| `docker-compose.yml` | Mosquitto, Kafka, Telegraf |
| `telegraf.conf` | อ่าน MQTT แล้วกระจายเข้า InfluxDB และ Kafka |
| `mosquitto.conf` | config ของ MQTT broker |
| `.env` | token ของ InfluxDB (ไม่ขึ้น git) |

คลิปทดสอบ (`*.mp4`, `*.mov`) และน้ำหนักโมเดล (`*.pt`) ไม่ได้เก็บใน repo เพราะไฟล์ใหญ่

## เอกสารออกแบบ

`docs/superpowers/specs/` เก็บเหตุผลเบื้องหลังการตัดสินใจ
โดยเฉพาะเรื่องโครงสร้างข้อมูลใน InfluxDB ที่แก้ย้อนหลังไม่ได้
ส่วน `docs/superpowers/plans/` เก็บแผนลงมือทำ

## ยังไม่ได้ทำ

สาย Kafka ต่อไปยัง consumer ที่ใช้ Python ML ทำนายว่าอีกกี่นาทีข้างหน้ารถจะติด
ตอนนี้ข้อมูลไหลเข้า Kafka topic `traffic-events` แล้วแต่ยังไม่มีใครอ่าน
ต้องรอให้สะสมข้อมูลใน InfluxDB ระยะหนึ่งก่อนจึงจะมี training data พอ
