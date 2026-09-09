# สายที่ 1: ส่งข้อมูลจราจรเข้า InfluxDB กลาง แล้วดูผลบน Grafana

วันที่: 2026-09-09

## เป้าหมาย

ทำให้ข้อมูลจราจรที่ `testmqtt.py` ตรวจจับได้ ไหลจาก MQTT ผ่าน Telegraf
ไปถึง InfluxDB กลางของอาจารย์ พร้อม tag และ timestamp ที่ถูกต้อง
แล้วดูผลย้อนหลังบน Grafana กลางได้

งานนี้เป็นฐานให้สายที่ 2 (Kafka → Python ML ทำนายรถติดล่วงหน้า) ซึ่งจะทำแยกต่างหาก
โครงสร้างข้อมูลที่ตกลงกันในเอกสารนี้คือสิ่งที่โมเดล ML จะมาอ่านใช้

## ขอบเขต

อยู่ในขอบเขต:

- แก้ `telegraf.conf` ให้ parse payload ถูกต้องและเขียนลง InfluxDB
- ย้าย token ออกจากไฟล์ที่ขึ้น git
- แก้ `testmqtt.py` สองจุดเล็ก ๆ ที่กระทบคุณภาพข้อมูล
- เขียน Flux query ของ dashboard ไว้ใน README
- commit ไฟล์ที่ยังค้างอยู่ใน working tree

ไม่อยู่ในขอบเขต:

- Kafka consumer และโมเดล ML (สายที่ 2)
- ปรับปรุงความแม่นยำของสูตรตัดสินความติดขัด
- รองรับหลายกล้อง
- รัน InfluxDB หรือ Grafana ในเครื่องตัวเอง

## สถาปัตยกรรม

```
testmqtt.py (YOLO + ByteTrack)  ── JSON ทุก 10 วิ ──▶  Mosquitto (local :1883)
                                                        topic: traffic/6620301002
                                                              │
                                                              ▼
                                                       Telegraf (local)
                                    ┌─────────────────────────┴─────────────────────────┐
                                    ▼                                                   ▼
                    InfluxDB 172.16.2.117:8086                            Kafka (local :9092)
                    bucket: mini_project ──▶ Grafana กลาง                 topic: traffic-events
                                                                          └▶ สายที่ 2 ทำทีหลัง
```

ไม่มี service ใหม่ใน `docker-compose.yml` ทั้ง InfluxDB และ Grafana เป็นของกลาง
ที่รันอยู่บนเครื่องอาจารย์แล้ว ของเดิมสามตัวคือ Mosquitto, Kafka, Telegraf เพียงพอ

## ปลายทาง InfluxDB

| รายการ | ค่า |
|---|---|
| URL | `http://172.16.2.117:8086` |
| organization | `my-org` |
| bucket | `mini_project` |
| retention | infinite (ตั้งไว้แล้วฝั่งเซิร์ฟเวอร์) |
| token | อยู่ใน `.env` ตัวแปร `INFLUX_TOKEN` ไม่ขึ้น git |

ตรวจสอบแล้วเมื่อ 2026-09-09 ว่าเซิร์ฟเวอร์ตอบ `/health` ด้วย HTTP 200 ภายใน 10 มิลลิวินาที
และ bucket `mini_project` มีอยู่จริง (orgID `e761e698e5720d2f`)

token ถูกจำกัดสิทธิ์ให้เห็นเฉพาะ bucket นี้ อ่าน API ของ org ไม่ได้
จึงยืนยันชื่อ org ว่าเป็น `my-org` ผ่าน API ไม่ได้ ต้องเชื่อตามที่อาจารย์แจ้ง
ถ้าเขียนแล้วได้ error ว่าไม่พบ organization ให้ใส่ orgID `e761e698e5720d2f`
แทนชื่อใน `organization` ของ `outputs.influxdb_v2` — endpoint รับทั้งชื่อและ ID

## โครงสร้างข้อมูล

| รายการ | ค่า |
|---|---|
| measurement | `traffic` |
| tags | `camera_id`, `student_id`, `topic` |
| fields | `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`, `slow_vehicle_ratio`, `congestion_level` |
| time | จากฟิลด์ `timestamp` ใน payload |

ความหมายของ `congestion_level` คือ 0 = FREE, 1 = MODERATE, 2 = HEAVY, 3 = JAM

`topic` เป็น tag ที่ `mqtt_consumer` ติดมาให้เองโดยไม่ต้องตั้งค่า มีค่าคงที่
`traffic/6620301002` จึงไม่มีผลเสีย ปล่อยไว้ตามนั้น

### tag `host` ต้องปิด

เพิ่มหลังจากทดสอบจริงเมื่อ 2026-09-09 ตอนเขียน spec ครั้งแรกยังไม่รู้เรื่องนี้

Telegraf ติด tag `host` มาให้ทุกจุดข้อมูลโดยอัตโนมัติ ซึ่งเมื่อรันใน container
ค่านี้คือ container ID เช่น `d2cc4f37e245` และ **เปลี่ยนทุกครั้งที่สร้าง container ใหม่**

InfluxDB ระบุ series ด้วยชุด tag ทั้งหมด พอ `host` เปลี่ยน ข้อมูลชุดใหม่จึงกลายเป็น
คนละ series กับชุดเก่า ผลคือกราฟใน Grafana ขาดเป็นท่อนและแสดงเป็นหลายเส้น
ส่วนโมเดล ML จะเห็นข้อมูลแตกเป็นหลายก้อนแทนที่จะเป็นอนุกรมเวลาเดียวต่อเนื่อง

แก้ด้วย `omit_hostname = true` ในส่วน `[agent]` ของ `telegraf.conf`

ข้อมูลทดสอบชุดแรกที่เขียนไปก่อนแก้ (ราว 07:41-07:42 UTC ของวันที่ 2026-09-09)
ยังมี tag `host` ติดอยู่และแยกเป็นคนละ series ปริมาณราวหนึ่งนาที
ไม่ได้ลบทิ้งเพราะเป็น bucket ของอาจารย์ที่ใช้ร่วมกันทั้งห้อง
การลบข้อมูลในนั้นควรถามเจ้าของก่อน

### เรื่อง type ของ field

parser `json` แปลงตัวเลขทุกตัวเป็น float และไม่มี option ให้บังคับเป็น integer
ดังนั้น `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi` และ `congestion_level`
จะถูกเก็บใน InfluxDB เป็น float (0.0, 1.0, 2.0) ไม่ใช่ int

ยอมรับได้ เพราะ value mapping ของ Grafana จับค่า 0.0 เป็น FREE ได้ปกติ
และโมเดล ML แปลงเป็น float เป็น input อยู่แล้ว
อย่าเสียเวลาหาวิธีบังคับ type กับ parser ตัวนี้ ถ้าจำเป็นจริงต้องเปลี่ยนไปใช้ `json_v2`
ซึ่งเราตัดสินใจไม่ใช้เพราะ config ยาวโดยไม่ได้ประโยชน์คุ้ม

**สำคัญ**: type ของ field ใน InfluxDB เปลี่ยนย้อนหลังไม่ได้ภายใน bucket เดียวกัน
ถ้าเคยเขียน float ไปแล้วมาเขียน int ทีหลัง จุดใหม่จะถูกปฏิเสธ
ตัดสินใจครั้งเดียวแล้วอยู่กับมัน

### ทำไมต้องมี tag `student_id`

bucket `mini_project` ใช้ร่วมกันทั้งห้อง และ `CAMERA_ID` ใน `testmqtt.py`
เป็นค่าคงที่ `CAM_BUILDING2_FL02` ซึ่งเพื่อนที่ใช้โค้ดต้นแบบเดียวกัน
มีโอกาสสูงที่จะส่งค่าเดียวกันมา

InfluxDB ระบุจุดข้อมูลด้วย measurement + tags + timestamp
ถ้าสามอย่างนี้ตรงกัน จุดใหม่จะ**เขียนทับจุดเดิมโดยไม่แจ้ง error**
ข้อมูลจะหายเงียบ ๆ และกู้คืนไม่ได้ การเติม tag นี้เป็นการเพิ่มโค้ดบรรทัดเดียว
เพื่อกันปัญหาที่แก้ย้อนหลังไม่ได้

### ทำไมต้องใช้ timestamp จาก payload

ถ้าไม่ตั้ง `json_time_key` Telegraf จะใช้เวลาที่ตัวเองได้รับข้อความแทน
ซึ่งคลาดจากเวลาที่กล้องตรวจจับจริงตามจังหวะ `flush_interval` และตามดีเลย์ของ MQTT
สำหรับข้อมูล time series ที่จะเอาไปเทรนโมเดลทำนายอนาคต ความถูกต้องของแกนเวลาคือทุกอย่าง

payload ส่ง timestamp เป็น ISO 8601 ที่ความละเอียดระดับวินาที ตรงกับรูปแบบ RFC3339

## รายละเอียดการเปลี่ยนแปลง

### 1. `.gitignore`

เพิ่มสองบรรทัด

- `.env` — กัน token หลุดขึ้น git
- `*.mov` — ปัจจุบัน `test.mov` ขนาด 1 GB อยู่ในโฟลเดอร์และยังไม่ถูก ignore
  ถ้าเผลอ `git add .` จะได้ commit ที่ push ไม่ขึ้นและลบยาก
  (ของเดิม ignore แค่ `*.mp4`)

### 2. `.env` และ `.env.example`

`.env` เก็บ `INFLUX_TOKEN` ตัวจริง ไม่ขึ้น git

`.env.example` ขึ้น git ได้ เป็นแม่แบบบอกว่าต้องตั้งตัวแปรอะไรบ้าง โดยไม่มีค่าจริง

### 3. `docker-compose.yml`

เพิ่ม `env_file: .env` ให้ service `telegraf` เพื่อให้ `${INFLUX_TOKEN}`
ใน `telegraf.conf` ถูกแทนค่าตอนรัน

### 4. `telegraf.conf`

ใน `[[inputs.mqtt_consumer]]` เพิ่ม

- `name_override = "traffic"` — ไม่งั้น measurement จะชื่อ `mqtt_consumer` ตาม default
- `tag_keys = ["camera_id", "student_id"]` — parser `json` ทิ้งค่า string ทุกตัวที่ไม่ระบุไว้
  ปัจจุบัน `camera_id` จึงหายไปทั้งหมด
- `json_time_key = "timestamp"` และ `json_time_format = "RFC3339"`

เพิ่ม block ใหม่ `[[outputs.influxdb_v2]]` ชี้ไป `http://172.16.2.117:8086`
โดยอ่าน token จาก `${INFLUX_TOKEN}`

`[[outputs.kafka]]` เดิมคงไว้ตามเดิม สายที่ 2 จะมาใช้ต่อ

### 5. `testmqtt.py`

แก้สองจุด

`level_code` ปัจจุบันคืน `None` เมื่อไม่มีรถใน ROI เลย ซึ่งกลายเป็น `null` ใน JSON
และถูก Telegraf ทิ้งไป ทำให้ time series ขาดเป็นช่วง
ในเชิงความหมายถนนที่ไม่มีรถคือถนนที่ไม่ติด ไม่ใช่ถนนที่ไม่รู้สภาพ
เปลี่ยนให้คืน `0` (FREE) ทำให้เส้นข้อมูลต่อเนื่องและโมเดล ML ไม่ต้องจัดการ missing value

`build_payload` เพิ่มฟิลด์ `student_id` ค่า `"6620301002"` (ค่าคงที่ระดับโมดูลเหมือน `CAMERA_ID`)

### 6. `README.md`

ข้อความปัจจุบันบอกว่า "ส่ง payload ขึ้น mqtt ทุก 3 วิ จากนั้น mqtt ส่งข้อมูลทุก 1 นาทีไป infulx db"
ซึ่งไม่ตรงกับโค้ด (`INTERVAL_SEC = 10`) และไม่ตรงกับ `telegraf.conf` (`flush_interval = "10s"`)
แก้ให้ตรงความจริงคือ 10 วินาทีตลอดสาย

เพิ่มวิธี setup (คัดลอก `.env.example` เป็น `.env` แล้วใส่ token, สั่ง `docker compose up -d`, รันสคริปต์)
และเพิ่ม Flux query ของทั้งสาม panel

### 7. commit ไฟล์ที่ค้าง

`docker-compose.yml`, `mosquitto.conf`, `telegraf.conf` ยังไม่ถูก track
ส่วน `detect_video.py` และ `mqtt_publish.py` ถูกลบแล้วแต่ยังไม่ commit
จัดการให้ working tree สะอาด

## Dashboard บน Grafana

Grafana เป็นของกลาง จึง provision อัตโนมัติจากฝั่งเราไม่ได้
เอกสารนี้จึงส่งมอบเป็น Flux query ที่คัดลอกไปวางในหน้าสร้าง panel ได้ทันที
เขียนไว้ใน README

ทุก query กรองด้วย `student_id` ของเราเสมอ เพื่อไม่ให้ข้อมูลของเพื่อนในห้องปนเข้ามา

สาม panel ที่ตกลงกัน

1. **Stat — สถานะปัจจุบัน** แสดง `congestion_level` ล่าสุดพร้อม value mapping
   0 → FREE เขียว, 1 → MODERATE เหลือง, 2 → HEAVY ส้ม, 3 → JAM แดง
   และแสดง `vehicles_in_roi` ล่าสุดคู่กัน
2. **Time series — จำนวนรถแยกประเภท** เส้น `car`, `motorcycle`, `bus`, `truck` ซ้อนกันตามเวลา
3. **State timeline — ระดับความติดขัด** แถบสีแนวนอนของ `congestion_level` ตามเวลา

## การตรวจสอบว่าทำงานได้จริง

ไม่ประกาศว่าเสร็จจนกว่าจะผ่านทุกข้อและได้เห็นผลลัพธ์จริง

1. `docker compose config` ผ่านโดยไม่มี error และเห็นว่า `INFLUX_TOKEN` ถูกแทนค่าแล้ว
2. `docker compose up -d` แล้ว log ของ Telegraf ไม่มี error เรื่องการเชื่อมต่อ InfluxDB
3. รัน `testmqtt.py` ให้ส่ง payload อย่างน้อย 3 รอบ
4. query กลับจาก InfluxDB ด้วย Flux แล้วต้องเห็น
   - measurement ชื่อ `traffic`
   - tag `camera_id` และ `student_id` มีค่าครบ ไม่หาย
   - timestamp ตรงกับเวลาที่สคริปต์พิมพ์ออก stdout ไม่ใช่เวลาที่ Telegraf รับ
   - field ครบทั้ง 7 ตัว และ `congestion_level` ไม่เป็น null แม้ตอนไม่มีรถ
5. แสดงผลลัพธ์ query ให้ผู้ใช้ดูเป็นหลักฐาน

## ข้อจำกัดที่รู้แล้วและจงใจไม่แก้

**ข้อมูลอยู่ที่เดียว** เขียนลง InfluxDB กลางของอาจารย์อย่างเดียว ไม่มีสำเนาในเครื่อง
ถ้าอาจารย์ล้าง bucket หรือปิดระบบหลังจบเทอม ข้อมูลสำหรับเทรนโมเดลสายที่ 2 จะหายไปด้วย
ผู้ใช้รับความเสี่ยงนี้แล้ว ถ้าต้องการสำรองภายหลัง เพิ่ม `[[outputs.influxdb_v2]]`
อีก block ชี้ไป InfluxDB ในเครื่องได้ Telegraf รองรับหลาย output อยู่แล้ว

**MQTT ไม่ reconnect ตอนสตาร์ท** ถ้า Mosquitto ยังไม่ขึ้นตอนรัน `testmqtt.py`
โค้ดจะพิมพ์ error แล้วรันต่อโดยที่ publish ไม่ออกเลย เพราะ `connect()` โยน exception
ก่อนถึง `loop_start()` แก้ได้ด้วย `connect_async` แต่ไม่ทำในรอบนี้
เพราะ broker อยู่เครื่องเดียวกันและขั้นตอนคือสั่ง `docker compose up -d` ก่อนอยู่แล้ว

**Telegraf buffer จำกัด** ถ้าต่อ InfluxDB ไม่ได้ Telegraf เก็บไว้ในหน่วยความจำตาม
`metric_buffer_limit` (default 10,000 จุด) ที่ความถี่ 10 วินาทีคือกันขาดช่วงได้ราว 27 ชั่วโมง
เพียงพอสำหรับโปรเจกต์เรียน เกินนั้นข้อมูลเก่าสุดจะถูกทิ้ง

**Token อยู่ในประวัติแชท** token ถูกวางลงในบทสนทนากับ Claude แล้ว
ตัวไฟล์จะไม่ขึ้น git แต่ถ้าต้องการความปลอดภัยเต็มที่ควรขอ token ใหม่จากอาจารย์

## แนวทางการเขียนโค้ด

ผู้ใช้ระบุให้ใช้ skill `ponytail` ตอนลงมือเขียนโค้ดจริง
คือเลือกทางที่สั้นและง่ายที่สุดที่ยังทำงานถูกต้อง
ใช้ความสามารถที่ Telegraf, Docker Compose และ paho-mqtt มีให้อยู่แล้ว
ไม่เขียนสิ่งที่ของเดิมทำได้ ไม่เพิ่ม dependency ใหม่ ไม่สร้าง abstraction เผื่ออนาคต

การเปลี่ยนแปลงทั้งหมดในเอกสารนี้เป็นการแก้ config และแก้โค้ดไม่กี่บรรทัด
ไม่มีไฟล์ Python ใหม่ ถ้าตอน implement พบว่าต้องเขียนโค้ดเยอะกว่านี้มาก
แปลว่าหลงทาง ให้กลับมาทบทวน

## สิ่งที่ทำต่อหลังจากนี้

สายที่ 2: Kafka consumer ที่ใช้ Python ML ทำนายว่าอีกกี่นาทีข้างหน้ารถจะติด
ต้องรอให้สายนี้สะสมข้อมูลใน InfluxDB ระยะหนึ่งก่อน จึงจะมี training data พอ
และจะ brainstorm เป็นโปรเจกต์แยกพร้อม spec ของตัวเอง
