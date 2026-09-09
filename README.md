# IOT_PROJECT — ตรวจจับสภาพจราจรจากวิดีโอ

ตรวจจับสภาพจราจรด้วย YOLO + ByteTrack แล้วส่งผลขึ้น MQTT
จากนั้น Telegraf กระจายออกสองทาง คือเข้า InfluxDB เพื่อดูบน Grafana
และเข้า Kafka ของวิชาโดยตรงเพื่อทำ ML ต่อ

```
                 testmqtt.py (YOLO + ByteTrack)
                             │
            ┌────────────────┴────────────────┐
            │ topic                           │ topic
            │ traffic/6620301002              │ iot/6620301002/traffic/<กล้อง>/events
            ▼                                 ▼
 Mosquitto ในเครื่อง (:1883)        VerneMQ กลาง (172.16.2.117:1883)
            │                                 │
            ▼                            (ยังไม่มีใครอ่าน)
      Telegraf
            │
   ┌────────┴─────────────────────┐
   ▼                              ▼
InfluxDB กลาง (:8086)      Kafka ของวิชา (172.16.2.117:9092)
bucket mini_project        topic traffic-events-6620301002
   │                              │
   ▼                              ▼
Grafana กลาง            [สายที่ 2 ML ทำนายรถติด]
```

การส่ง MQTT ไป VerneMQ กลางยังคงไว้อยู่ แต่ตอนนี้ไม่มี Kafka Connect
ตัวไหนอ่าน topic นั้นแล้ว ดูหัวข้อ [เส้นทางเข้า Kafka ของวิชา](#เส้นทางเข้า-kafka-ของวิชา)

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
| `--loop` | – | เล่นไฟล์วิดีโอวนซ้ำเมื่อจบคลิป (ใช้กับกล้องสดไม่ได้) |

### เรื่อง `--loop`

ใช้เมื่ออยากให้ข้อมูลไหลต่อเนื่องโดยไม่ต้องมานั่งกดรันใหม่ เช่นทดสอบว่าท่อข้อมูล
ทนการรันยาว ๆ ได้ไหม หรือเตรียมข้อมูลไว้เดโมตอนนำเสนอ

```bash
python testmqtt.py test.mov --loop
```

ตอนภาพกระโดดกลับต้นคลิป โค้ดจะล้าง track ที่ติดตามอยู่ทิ้งก่อน ไม่งั้นระบบ
จะคิดว่ารถวิ่งข้ามจอในเฟรมเดียวแล้วคำนวณความเร็วพุ่งผิด

ผลข้างเคียงคือ**แต่ละรอบของการวนจะมีจุดข้อมูลเพี้ยนหนึ่งจุด** เพราะหลังล้าง track
หน้าต่างคำนวณความเร็วจะว่างชั่วคราว ทำให้ `slow_vehicle_ratio` ต่ำผิดปกติ
และ `congestion_level` ตกไปเป็น 0 หนึ่งครั้ง ก่อนจะกลับมาปกติในรอบถัดไป
วัดจริงได้ประมาณนี้

```
15:44:39  slow=0.78  รถ=15  level=3
15:44:46  slow=0.37  รถ=14  level=2
15:44:52  slow=0.04  รถ=11  level=0   <-- รอยต่อของการวนคลิป
15:44:59  slow=0.66  รถ=14  level=3
15:45:05  slow=0.75  รถ=16  level=3
```

ดีกว่าปล่อยให้ความเร็วพุ่งผิด แต่ถ้าเอาข้อมูลไปวิเคราะห์ต้องรู้ว่ามีจุดพวกนี้ปนอยู่

**อย่าใช้ข้อมูลจากคลิปวนซ้ำไปเทรนโมเดลทำนาย** คลิปเดิมวนทุก N นาทีให้รูปแบบเดิมซ้ำ ๆ
โมเดลจะเรียนได้แค่ว่ารถติดวนเป็นรอบตามความยาวคลิป ซึ่งไม่ใช่ความจริงของถนน
การทำนายล่วงหน้าต้องอาศัยรูปแบบตามเวลาจริง เช่นชั่วโมงเร่งด่วนต่างจากดึกสงัดยังไง
ซึ่งต้องได้จากกล้องสดเท่านั้น

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

## เส้นทางเข้า Kafka ของวิชา

Telegraf เขียนเข้า Kafka ของอาจารย์โดยตรงที่ `172.16.2.117:9092`
topic `traffic-events-6620301002` ไม่ต้องผ่านตัวกลางอะไรอีก

### เคยส่งตรงไม่ได้ ตอนนี้ได้แล้ว

เดิม broker ประกาศตัวเอง (`advertised.listeners`) ว่าอยู่ที่ `localhost:9092`
ซึ่งเครื่องอื่นเข้าไม่ถึง client จะเด้งไปหา localhost ของตัวเองแล้ว timeout
ตอนนั้นจึงต้องอ้อมด้วยการ publish MQTT ไป VerneMQ กลาง
แล้วให้ Kafka Connect บนเครื่องอาจารย์ดึงเข้า Kafka ให้

วันที่ 2026-09-09 อาจารย์แก้เป็น `172.16.2.117:9092` และรีเซ็ตระบบ
ซึ่งลบ connector ทั้งหมดทิ้งไปด้วย จึงเปลี่ยนมาส่งตรงแทน

เช็กค่าปัจจุบันได้ที่

```bash
curl -s "http://172.16.2.117:8080/api/clusters/IoT-Kafka-Cluster/brokers/1/configs" \
  | python3 -c "import sys,json;[print(c['name'],'=',c['value']) for c in json.load(sys.stdin) if c['name']=='advertised.listeners']"
```

ถ้าวันไหนกลับไปเป็น `localhost:9092` อีก จะส่งตรงไม่ได้ทันที
ต้องกลับไปใช้เส้นทาง MQTT แล้วสร้าง connector ใหม่

### รูปแบบข้อความใน Kafka

Telegraf ห่อข้อมูลเป็นรูปแบบของตัวเอง ไม่ใช่ payload ดิบแบบที่ส่งขึ้น MQTT

```json
{
  "fields": {"bus": 0, "car": 6, "congestion_level": 0, "motorcycle": 0,
             "slow_vehicle_ratio": 0.02, "truck": 0, "vehicles_in_roi": 6},
  "name": "traffic_6620301002",
  "tags": {"camera_id": "CAM_BUILDING2_FL02", "student_id": "6620301002",
           "topic": "traffic/6620301002"},
  "timestamp": 1788947816
}
```

ต่างจาก payload ดิบตรงที่ค่าถูกแยกเป็น `fields` กับ `tags` และ `timestamp`
เป็นตัวเลข Unix ไม่ใช่สตริง ISO ตัวอ่านในสายที่ 2 ต้องแกะตามรูปแบบนี้

อยากได้เวลาเป็น ISO เหมือนเดิมให้เติมใน `[[outputs.kafka]]`

```toml
json_timestamp_format = "2006-01-02T15:04:05Z07:00"
```

### MQTT ไป VerneMQ กลางยังส่งอยู่

`testmqtt.py` ยังส่งขึ้น VerneMQ ที่ `172.16.2.117:1883` topic
`iot/6620301002/traffic/<camera_id>/events` ตามคอนเวนชันของวิชา
(ชนิดที่เห็นใช้กันมี `events`, `metrics`, `health`)

ตอนนี้ยังไม่มี Kafka Connect ตัวไหนอ่าน topic นั้น ข้อมูลจึงไปไม่ถึง Kafka ทางนั้น
คงไว้เพราะอาจารย์อาจสร้าง connector กลับมา และการส่ง MQTT ก็ไม่ได้เสียหายอะไร

### ดูข้อมูลที่เข้า Kafka แล้ว

ใช้ Kafka UI ที่ http://172.16.2.117:8080 เลือกคลัสเตอร์ `IoT-Kafka-Cluster`
แล้วเปิด topic `traffic-events-6620301002`

หรือนับจำนวนข้อความจากบรรทัดคำสั่ง

```bash
curl -s "http://172.16.2.117:8080/api/clusters/IoT-Kafka-Cluster/topics/traffic-events-6620301002" \
  | python3 -c "import sys,json;[print(p['offsetMax']-p['offsetMin'],'ข้อความ') for p in json.load(sys.stdin)['partitions']]"
```


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

## Dashboard บน Grafana

สร้าง panel แล้วเลือก datasource เป็น InfluxDB ที่ชี้ไป bucket `mini_project`
จากนั้นคัดลอก query ข้างล่างไปวาง

### Panel 1 — สถานะปัจจุบัน (Stat)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic_6620301002")
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
  |> filter(fn: (r) => r._measurement == "traffic_6620301002")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => contains(value: r._field, set: ["car", "motorcycle", "bus", "truck"]))
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

ตั้ง Graph styles เป็น Stacked เพื่อให้เห็นสัดส่วนของแต่ละประเภท

### Panel 3 — ไทม์ไลน์ระดับความติดขัด (State timeline)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic_6620301002")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "congestion_level")
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
```

ใช้ Value mappings ชุดเดียวกับ Panel 1

## ดักฟังข้อมูลระหว่างทาง

ข้อมูลผ่านหลายทอดกว่าจะถึงปลายทาง ดักฟังได้ทุกจุดเพื่อหาว่าขาดตรงไหน
ไล่จากต้นทางไปปลายทาง จุดสุดท้ายที่ยังเห็นข้อมูลคือจุดที่ปัญหาอยู่ถัดจากนั้น

**ทุกคำสั่งในหัวข้อนี้ต้องเปิดสคริปต์ตรวจจับทิ้งไว้อีกเทอร์มินัลหนึ่ง**
ไม่งั้นจะไม่มีอะไรวิ่งให้ดักฟัง แล้วจะเข้าใจผิดว่าระบบพัง

### จุดที่ 1 เทอร์มินัลที่รันสคริปต์ — พิสูจน์ไม่ได้

JSON ที่พิมพ์ออกมาบอกแค่ว่าสคริปต์ตั้งใจจะส่ง ไม่ได้บอกว่าส่งถึง
เพราะใน `emit()` มันสั่ง `print()` ก่อนแล้วค่อย `publish()` ทีหลัง
แถมใช้ `qos=0` คือส่งแล้วไม่รอคำยืนยันจาก broker
ถ้าเห็นบรรทัด `ส่ง MQTT ไม่สำเร็จ` แปลว่าพังแน่ แต่ถ้าไม่เห็นก็ยังไม่การันตี

### จุดที่ 2 ดักฟัง MQTT ที่ broker

ใช้เครื่องมือในตัวคอนเทนเนอร์ ไม่ต้องติดตั้งอะไรเพิ่ม

```bash
docker compose exec mosquitto mosquitto_sub -t 'traffic/6620301002' -v
```

คำสั่งจะค้างรอ พอมีข้อความจริงจะเด้งขึ้นมาทันที กด Ctrl+C เพื่อออก

```
traffic/6620301002 {"timestamp": "2026-09-09T14:56:45+07:00", "camera_id": "CAM_BUILDING2_FL02",
"student_id": "6620301002", "car": 6, ..., "congestion_level": 0}
```

นี่คือสิ่งที่ Mosquitto ได้รับจริง ไม่ใช่สิ่งที่สคริปต์อ้าง
ถ้าเห็นข้อความตรงนี้แปลว่าฝั่งส่งทำงานถูกแล้ว ปัญหา (ถ้ามี) อยู่หลังจากนี้

อยากดูทุก topic ในเครื่องใช้ `-t '#'` แทน จะเห็นของทุกคนที่ส่งเข้า broker ตัวนี้

### จุดที่ 3 ดักฟังที่ Telegraf

โหมด `--test` จะอ่าน input จริงแล้วพิมพ์ผลออกหน้าจอ **โดยไม่เขียนลงปลายทางเลย**
(จะขึ้นบรรทัด `Outputs are not used in testing mode!` ยืนยันให้)

```bash
docker compose exec telegraf telegraf --config /etc/telegraf/telegraf.conf --test --test-wait 20
```

รอ 20 วินาทีแล้วจะได้ line protocol แบบนี้

```
> traffic_6620301002,camera_id=CAM_BUILDING2_FL02,student_id=6620301002,topic=traffic/6620301002
  bus=0,car=6,congestion_level=0,motorcycle=0,slow_vehicle_ratio=0.02,truck=0,vehicles_in_roi=6 1788941250000000000
```

**นี่คือจุดที่มีประโยชน์ที่สุดเวลาแก้ปัญหา** เพราะเห็นครบในบรรทัดเดียวว่า

- ชื่อ measurement ถูกไหม (ต้องเป็น `traffic_6620301002` ไม่ใช่ `mqtt_consumer`)
- tag มาครบไหม (ส่วนก่อนช่องว่างแรก ต้องมี `camera_id` และ `student_id`)
- field มาครบ 7 ตัวไหม (ส่วนกลาง)
- timestamp เป็นเวลาที่กล้องตรวจจับไหม (ตัวเลขท้ายสุด หน่วยนาโนวินาที)

ถ้า tag หายแปลว่า `tag_keys` ใน `telegraf.conf` ผิด ถ้าชื่อผิดแปลว่า `name_override` ผิด

ดู log ปกติของ Telegraf ที่รันอยู่จริง

```bash
docker compose logs -f telegraf
```

มองหาบรรทัดที่ขึ้นต้นด้วย `E!` โดยเฉพาะ unauthorized (token ผิด)
หรือ connection refused (ต่อเซิร์ฟเวอร์อาจารย์ไม่ได้) ถ้าเงียบคือปกติ

### จุดที่ 4 ดักฟังที่ Kafka ของวิชา

ดูว่า Telegraf ส่งอะไรเข้า Kafka บ้าง (สายที่ 2 จะมาอ่านตรงนี้)
ต้องรันจากคอนเทนเนอร์เปล่า **ห้ามรันจากคอนเทนเนอร์ kafka ในเครื่องเรา**

```bash
docker run --rm apache/kafka:latest /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server 172.16.2.117:9092 \
  --topic traffic-events-6620301002 --from-beginning
```

`--from-beginning` คืออ่านตั้งแต่ข้อความแรกสุดที่เคยเข้ามา ถ้าอยากดูเฉพาะของใหม่ให้ตัดออก
กด Ctrl+C เพื่อออก

**เหตุผลที่ต้องใช้คอนเทนเนอร์เปล่า** ถ้ารัน `docker compose exec kafka ...` แล้วชี้ไป
`172.16.2.117:9092` broker จะตอบกลับมาว่าโหนดอยู่ที่ไหน ถ้าค่าที่ตอบมาคือ `localhost`
client จะเด้งไปอ่าน Kafka ในเครื่องเราเองโดยไม่มี error เตือน แล้วเห็นข้อมูลผิดตัว
เคยพลาดมาแล้วตอนตรวจสอบระบบ

### จุดที่ 5 ปลายทาง InfluxDB

```bash
set -a && . ./.env && set +a
curl -s -XPOST "http://172.16.2.117:8086/api/v2/query?org=my-org" \
  -H "Authorization: Token $INFLUX_TOKEN" \
  -H "Content-Type: application/vnd.flux" \
  -H "Accept: application/csv" \
  -d 'from(bucket:"mini_project")
      |> range(start: -30m)
      |> filter(fn: (r) => r._measurement == "traffic_6620301002" and r.student_id == "6620301002")
      |> last()'
```

ถ้ามีแถวข้อมูลกลับมาคือถึงปลายทางแน่นอน ถ้าได้ผลว่างให้ไล่ย้อนจากจุดที่ 4 ขึ้นไป

ดูใน InfluxDB UI ให้เลือก bucket `mini_project` แล้วเลือก `_measurement`
เป็น `traffic_6620301002` และ **ขยายช่วงเวลาเป็น Past 1h**
ค่าเริ่มต้นมักเป็น 5 นาทีซึ่งจะว่างเปล่าถ้าตอนนั้นไม่ได้เปิดสคริปต์ทิ้งไว้

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
