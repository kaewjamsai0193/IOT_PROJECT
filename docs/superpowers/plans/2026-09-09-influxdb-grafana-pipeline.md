# แผน implementation: ส่งข้อมูลจราจรเข้า InfluxDB กลางและดูผลบน Grafana

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ทำให้ข้อมูลจราจรจาก `testmqtt.py` ไหลผ่าน MQTT และ Telegraf ไปถึง InfluxDB กลางของอาจารย์ พร้อม tag `camera_id`/`student_id` และ timestamp ที่ถูกต้อง แล้วดูผลบน Grafana กลางได้

**Architecture:** ไม่เพิ่ม service ใหม่ใน Docker เพราะ InfluxDB และ Grafana เป็นของกลางที่รันอยู่แล้ว งานทั้งหมดคือแก้ config ของ Telegraf ให้ parse payload ถูกต้องแล้วเขียนออกสองทาง (InfluxDB กลาง และ Kafka ในเครื่องที่สายที่ 2 จะมาใช้) บวกกับแก้ `testmqtt.py` สามจุดเล็ก ๆ และย้าย token ออกจากไฟล์ที่ขึ้น git

**Tech Stack:** Telegraf, Mosquitto, Kafka, Docker Compose, InfluxDB 2.x (Flux), Python 3 + paho-mqtt 2.1.0

**Spec:** `docs/superpowers/specs/2026-09-09-influxdb-grafana-pipeline-design.md`

## Global Constraints

- **ใช้ skill `ponytail` ก่อนแตะโค้ดหรือ config ทุกครั้ง** เลือกทางที่สั้นและง่ายที่สุดที่ยังทำงานถูกต้อง
- **ห้ามเพิ่ม dependency ใหม่** เครื่องนี้ไม่มี `pytest` และเราจะไม่ลง ใช้ `python3 -c` ตรวจแทน
- **ห้ามให้ token ปรากฏในไฟล์ที่ขึ้น git** repo นี้ public อยู่ที่ `github.com/kaewjamsai0193/IOT_PROJECT`
- ปลายทาง InfluxDB: URL `http://172.16.2.117:8086`, organization `my-org`, bucket `mini_project`
- ถ้าเขียนแล้วได้ error ว่าไม่พบ organization ให้ใส่ orgID `e761e698e5720d2f` แทนชื่อ
- measurement: `traffic` / tags: `camera_id`, `student_id` / student_id = `6620301002`
- ความถี่ส่งข้อมูล 10 วินาทีตลอดสาย ห้ามแก้ `INTERVAL_SEC`
- ตอบเป็นภาษาไทย รวมถึงข้อความ commit
- ทุก commit ระบุไฟล์เป็น path ชัดเจน **ห้ามใช้ `git add .` หรือ `git add -A`** เพราะ `test.mov` ขนาด 1 GB และ `.env` อยู่ในโฟลเดอร์เดียวกัน

## File Structure

| ไฟล์ | สถานะ | หน้าที่ |
|---|---|---|
| `.gitignore` | แก้ | กัน `.env` และ `*.mov` ไม่ให้ขึ้น git |
| `.env` | สร้าง (ไม่ขึ้น git) | เก็บ `INFLUX_TOKEN` ตัวจริง |
| `.env.example` | สร้าง (ขึ้น git) | แม่แบบบอกว่าต้องตั้งตัวแปรอะไร โดยไม่มีค่าจริง |
| `docker-compose.yml` | แก้ + track ใหม่ | ส่ง `.env` เข้า container telegraf |
| `telegraf.conf` | แก้ + track ใหม่ | parse payload และเขียนออก InfluxDB กับ Kafka |
| `mosquitto.conf` | track ใหม่ | config broker (ไม่ต้องแก้เนื้อหา) |
| `testmqtt.py` | แก้ + track ใหม่ | เพิ่ม `student_id` และเลิกส่ง `congestion_level` เป็น null |
| `README.md` | เขียนใหม่ | วิธี setup และ Flux query ของทั้ง 3 panel |
| `detect_video.py`, `mqtt_publish.py` | ลบ (commit การลบ) | ถูกแทนที่ด้วย `testmqtt.py` แล้ว |

---

### Task 1: กัน token และวิดีโอ 1 GB ไม่ให้หลุดขึ้น git

ทำเป็นงานแรกเสมอ เพราะขั้นตอนนี้สร้างไฟล์ `.env` ที่มี token อยู่จริง
ถ้า `.gitignore` ยังไม่กันไว้ก่อน มีโอกาสเผลอ commit ขึ้น repo สาธารณะ

**Files:**
- Modify: `.gitignore`
- Create: `.env` (ไม่ขึ้น git)
- Create: `.env.example`

**Interfaces:**
- Consumes: ไม่มี เป็นงานแรก
- Produces: ตัวแปร environment ชื่อ `INFLUX_TOKEN` ที่ Task 3 จะอ้างถึงใน `telegraf.conf` ผ่าน `${INFLUX_TOKEN}`

- [ ] **Step 1: ยืนยันว่าตอนนี้ยังไม่ปลอดภัย (นี่คือการทดสอบที่ต้องเห็นว่า "ล้มเหลว" ก่อน)**

```bash
git check-ignore -v .env test.mov
```

Expected: ไม่พิมพ์อะไรเลย และ exit code เป็น 1 แปลว่าทั้งสองไฟล์ยัง **ไม่ถูก** ignore

- [ ] **Step 2: แก้ `.gitignore`**

เปลี่ยนบล็อกวิดีโอเดิมและเพิ่มบล็อกความลับไว้บนสุด ผลลัพธ์คือไฟล์นี้

```gitignore
# ความลับ ห้ามขึ้น git เด็ดขาด repo นี้เป็น public
.env

# วิดีโอทดสอบ ใหญ่เกินกว่าจะเก็บใน git
*.mp4
*.mov

# น้ำหนักโมเดล YOLO โหลดใหม่ได้เองจาก ultralytics ตอนรันครั้งแรก
*.pt

# เอกสารอ้างอิง ไม่ใช่ส่วนหนึ่งของโค้ด
*.pdf

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# ไฟล์สำรองที่แก้เอง
*.bak
```

- [ ] **Step 3: ตรวจว่าตอนนี้ปลอดภัยแล้ว**

```bash
git check-ignore -v .env test.mov
```

Expected: พิมพ์สองบรรทัดชี้ว่ากฎข้อไหนใน `.gitignore` จับไฟล์ไหน exit code เป็น 0

- [ ] **Step 4: สร้าง `.env.example`**

```bash
cat > .env.example <<'EOF'
# คัดลอกไฟล์นี้เป็น .env แล้วใส่ token จริงที่อาจารย์แจก
# .env ถูก gitignore ไว้แล้ว ห้าม commit ขึ้น repo
INFLUX_TOKEN=
EOF
```

- [ ] **Step 5: สร้าง `.env` พร้อม token จริง**

สร้างไฟล์ `.env` ที่มีบรรทัดเดียวคือ `INFLUX_TOKEN=` ตามด้วย token ที่อาจารย์แจก

**token ตัวจริงอยู่ในบทสนทนา ไม่เขียนไว้ในเอกสารนี้เพราะเอกสารนี้ขึ้น git สาธารณะ**
ผู้ที่ execute ต้องหยิบค่าจากข้อความที่ผู้ใช้ส่งมา
ตรวจว่าหยิบมาครบด้วยความยาว ต้องได้ 88 ตัวอักษรและลงท้ายด้วย `==`

```bash
python3 -c "print(len(open('.env').read().split('=',1)[1].strip()))"
```

Expected: `88`

ห้ามพิมพ์ token ลงในไฟล์อื่นใดนอกจาก `.env`

- [ ] **Step 6: ตรวจว่า git มองไม่เห็น `.env`**

```bash
git status --short
```

Expected: ไม่มีบรรทัดของ `.env` และไม่มีบรรทัดของ `test.mov`
ต้องเห็น `.env.example` เป็น `??` และ `.gitignore` เป็น ` M`

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example
git commit -m "กัน .env และไฟล์ .mov ไม่ให้ขึ้น git

repo นี้ public บน GitHub และ .env จะเก็บ token ของ InfluxDB
ส่วน test.mov ขนาด 1 GB เดิมไม่ถูก ignore เพราะกฎเดิมครอบแค่ *.mp4
เพิ่ม .env.example เป็นแม่แบบให้รู้ว่าต้องตั้งตัวแปรอะไร"
```

---

### Task 2: เพิ่ม student_id และเลิกส่ง congestion_level เป็น null

**Files:**
- Modify: `testmqtt.py:17` (เพิ่มค่าคงที่), `testmqtt.py:52-55` (`level_code`), `testmqtt.py:197-209` (`build_payload`)

**Interfaces:**
- Consumes: ไม่มี
- Produces: payload JSON ที่มีคีย์ `student_id` (string) เพิ่มขึ้นมา และคีย์ `congestion_level` ที่เป็น int เสมอ ไม่มี null — Task 3 จะตั้ง `tag_keys` ใน Telegraf ให้ตรงกับชื่อคีย์นี้

- [ ] **Step 1: เขียนการทดสอบที่ต้องล้มเหลวก่อน**

สร้างไฟล์ชั่วคราว `/tmp/check_payload.py` (ไม่ commit ไฟล์นี้)

```python
import testmqtt as t

empty = {
    "counts": {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0},
    "occ": 0.0,
    "slow": 0.0,
}
busy = {
    "counts": {"car": 8, "motorcycle": 3, "bus": 0, "truck": 1},
    "occ": 12.0,
    "slow": 0.9,
}

assert t.level_code(0.0, 0) == 0, "ถนนว่างต้องเป็น FREE (0) ไม่ใช่ None"
assert t.level_code(0.9, 10) == 3, "รถช้า 90% ต้องเป็น JAM (3)"

p = t.build_payload(empty)
assert p["student_id"] == "6620301002", "payload ต้องมี student_id"
assert p["congestion_level"] == 0, "ตอนไม่มีรถ congestion_level ต้องเป็น 0 ไม่ใช่ None"

q = t.build_payload(busy)
assert q["congestion_level"] == 3
assert q["camera_id"] == "CAM_BUILDING2_FL02"
assert q["vehicles_in_roi"] == 12

print("ผ่านทั้งหมด")
```

- [ ] **Step 2: รันให้เห็นว่าล้มเหลว**

```bash
python3 /tmp/check_payload.py
```

Expected: FAIL ด้วย `AssertionError: ถนนว่างต้องเป็น FREE (0) ไม่ใช่ None`

- [ ] **Step 3: เพิ่มค่าคงที่ `STUDENT_ID`**

ที่ `testmqtt.py` บรรทัด 17 เดิมคือ

```python
CAMERA_ID = "CAM_BUILDING2_FL02"
```

เปลี่ยนเป็น

```python
CAMERA_ID = "CAM_BUILDING2_FL02"
STUDENT_ID = "6620301002"
```

- [ ] **Step 4: แก้ `level_code` ให้ถนนว่างเป็น FREE**

บรรทัด 52-55 เดิมคือ

```python
def level_code(slow, n_vehicles):
  if n_vehicles >= MIN_VEHICLES:
    return next(i for i, (lim, _) in enumerate(LEVELS) if slow * 100 < lim)
  return 0 if n_vehicles > 0 else None
```

เปลี่ยนบรรทัดสุดท้ายเป็น

```python
def level_code(slow, n_vehicles):
  if n_vehicles >= MIN_VEHICLES:
    return next(i for i, (lim, _) in enumerate(LEVELS) if slow * 100 < lim)
  return 0
```

ถนนที่ไม่มีรถคือถนนที่ไม่ติด การคืน `None` ทำให้ Telegraf ทิ้งฟิลด์นั้น
กราฟใน Grafana จะขาดเป็นช่วง และโมเดล ML ในสายที่ 2 จะเจอ missing value เต็มไปหมด

- [ ] **Step 5: เพิ่ม `student_id` ลง payload**

ที่ `build_payload` บรรทัด 201 เดิมคือ

```python
      "camera_id": CAMERA_ID,
```

เปลี่ยนเป็น

```python
      "camera_id": CAMERA_ID,
      "student_id": STUDENT_ID,
```

- [ ] **Step 6: รันการทดสอบให้ผ่าน**

```bash
python3 /tmp/check_payload.py
```

Expected: พิมพ์ `ผ่านทั้งหมด` และ exit code 0

- [ ] **Step 7: ดู payload จริงด้วยตาอีกครั้ง**

```bash
python3 -c "
import json, testmqtt as t
print(json.dumps(t.build_payload({'counts':{'car':4,'motorcycle':1,'bus':0,'truck':0},'occ':5.0,'slow':0.7}), ensure_ascii=False, indent=2))
"
```

Expected: JSON ที่มีครบ 10 คีย์ ได้แก่ `timestamp`, `camera_id`, `student_id`,
`car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`, `slow_vehicle_ratio`, `congestion_level`
โดย `student_id` เป็น `"6620301002"` และ `congestion_level` เป็นตัวเลข ไม่ใช่ null

- [ ] **Step 8: Commit**

```bash
git add testmqtt.py
git commit -m "เพิ่ม student_id ลง payload และเลิกส่ง congestion_level เป็น null

bucket ของ InfluxDB ใช้ร่วมกันทั้งห้อง และ CAMERA_ID เป็นค่าคงที่ที่เพื่อน
ซึ่งใช้โค้ดต้นแบบเดียวกันมีสิทธิ์ส่งค่าซ้ำ ถ้า tag กับ timestamp ตรงกัน
InfluxDB จะเขียนทับกันเงียบ ๆ จึงต้องมี student_id เป็นตัวแยก

ส่วน level_code เดิมคืน None ตอน ROI ไม่มีรถ ทำให้ Telegraf ทิ้งฟิลด์นั้น
กราฟขาดเป็นช่วงและโมเดล ML จะเจอ missing value
ถนนที่ไม่มีรถคือถนนที่ไม่ติด จึงคืน 0 (FREE)"
```

---

### Task 3: ให้ Telegraf เขียนข้อมูลเข้า InfluxDB กลาง

งานหลักของแผนนี้ รวม config ของ Telegraf และ Docker ไว้ด้วยกัน
เพราะแยก commit แล้วทดสอบไม่ได้ ต้องมีทั้งคู่ถึงจะเขียนข้อมูลออกไปได้จริง

**Files:**
- Modify: `telegraf.conf`
- Modify: `docker-compose.yml`
- Track ใหม่: `telegraf.conf`, `docker-compose.yml`, `mosquitto.conf`

**Interfaces:**
- Consumes: ตัวแปร `INFLUX_TOKEN` จาก Task 1 และคีย์ `student_id` ใน payload จาก Task 2
- Produces: จุดข้อมูลใน bucket `mini_project` measurement `traffic` ที่ Grafana ใน Task 4 จะ query

- [ ] **Step 1: ยืนยันว่าตอนนี้ยังไม่มีข้อมูลของเราใน InfluxDB (การทดสอบที่ต้องล้มเหลวก่อน)**

```bash
set -a && . ./.env && set +a
curl -s -XPOST "http://172.16.2.117:8086/api/v2/query?org=my-org" \
  -H "Authorization: Token $INFLUX_TOKEN" \
  -H "Content-Type: application/vnd.flux" \
  -H "Accept: application/csv" \
  -d 'from(bucket:"mini_project")
      |> range(start: -1h)
      |> filter(fn: (r) => r._measurement == "traffic" and r.student_id == "6620301002")
      |> last()'
```

Expected: ผลลัพธ์ว่าง ไม่มีแถวข้อมูล เพราะยังไม่เคยเขียน measurement `traffic` เข้าไป

- [ ] **Step 2: เขียน `telegraf.conf` ใหม่ทั้งไฟล์**

```toml
[agent]
  interval = "10s"
  round_interval = true
  flush_interval = "10s"

[[inputs.mqtt_consumer]]
  servers = ["tcp://mosquitto:1883"]
  topics = ["traffic/6620301002"]
  data_format = "json"
  # ไม่ตั้งชื่อ measurement จะกลายเป็น mqtt_consumer ตาม default
  name_override = "traffic"
  # parser json ทิ้งค่า string ทุกตัวที่ไม่ระบุไว้ตรงนี้
  # ถ้าไม่ใส่ camera_id กับ student_id จะหายไปทั้งคู่
  tag_keys = ["camera_id", "student_id"]
  # ใช้เวลาที่กล้องตรวจจับ ไม่ใช่เวลาที่ Telegraf ได้รับข้อความ
  json_time_key = "timestamp"
  json_time_format = "RFC3339"

[[outputs.influxdb_v2]]
  urls = ["http://172.16.2.117:8086"]
  token = "${INFLUX_TOKEN}"
  organization = "my-org"
  bucket = "mini_project"

[[outputs.kafka]]
  brokers = ["kafka:29092"]
  topic = "traffic-events"
  data_format = "json"
```

- [ ] **Step 3: ให้ container telegraf อ่าน `.env`**

ใน `docker-compose.yml` ที่ service `telegraf` เพิ่มบรรทัด `env_file: .env`
ผลลัพธ์ของ service นี้คือ

```yaml
  telegraf:
    image: telegraf:latest
    container_name: telegraf
    restart: unless-stopped
    env_file: .env
    depends_on:
      - mosquitto
      - kafka
    volumes:
      - ./telegraf.conf:/etc/telegraf/telegraf.conf:ro
```

- [ ] **Step 4: ตรวจ syntax ของ compose**

```bash
docker compose config --quiet && echo "compose syntax ผ่าน"
```

Expected: พิมพ์ `compose syntax ผ่าน` โดยไม่มี error

หมายเหตุ คำสั่งนี้ตรวจได้แค่รูปแบบไฟล์ ค่าจาก `env_file` จะไม่ถูกแทนลงในผลลัพธ์
จึงยังบอกไม่ได้ว่า token เข้าถึง container จริงหรือไม่ ต้องไปตรวจใน Step 5

- [ ] **Step 5: รีสตาร์ตแล้วตรวจว่า token เข้าถึง container จริง**

```bash
docker compose up -d
sleep 10
docker compose exec telegraf sh -c 'if [ -n "$INFLUX_TOKEN" ]; then echo "INFLUX_TOKEN เข้าถึง container แล้ว ความยาว ${#INFLUX_TOKEN} ตัวอักษร"; else echo "ไม่พบ INFLUX_TOKEN ใน container"; fi'
```

Expected: พิมพ์ `INFLUX_TOKEN เข้าถึง container แล้ว ความยาว 88 ตัวอักษร`

คำสั่งนี้ตรวจว่ามีค่าโดยไม่พิมพ์ตัว token ออกมา ถ้าได้ `ไม่พบ INFLUX_TOKEN`
แปลว่า `env_file` ไม่ทำงาน ให้กลับไปตรวจ Step 3 และรูปแบบของ `.env` ใน Task 1 Step 5
(ต้องเป็น `INFLUX_TOKEN=ค่า` บรรทัดเดียว ไม่มีช่องว่างคร่อม `=` ไม่มีเครื่องหมายคำพูด)

- [ ] **Step 6: ดู log ของ Telegraf**

```bash
docker compose logs --tail 40 telegraf
```

Expected: เห็นบรรทัดที่บอกว่าโหลด `outputs.influxdb_v2` และ `outputs.kafka` แล้ว
และ **ไม่มี** บรรทัด `E!` ที่พูดถึง unauthorized, connection refused หรือ organization not found

ถ้าเจอ `organization not found` ให้เปลี่ยน `organization = "my-org"` เป็น
`organization = "e761e698e5720d2f"` แล้วรีสตาร์ตใหม่ (orgID นี้ตรวจสอบแล้วว่าถูกต้อง)

- [ ] **Step 7: ส่งข้อมูลจริงเข้าไป**

```bash
python3 testmqtt.py test.mov --no-show
```

ปล่อยให้รันจนเห็น payload พิมพ์ออกมาอย่างน้อย 3 ก้อน (ราว 30-40 วินาที) แล้วกด Ctrl+C

Expected: เห็น JSON พิมพ์ออก stdout โดยแต่ละก้อนมี `student_id` และ `congestion_level` ที่ไม่ใช่ null
**จดเวลาใน field `timestamp` ของก้อนสุดท้ายไว้** จะใช้เทียบใน Step 8

- [ ] **Step 8: query กลับจาก InfluxDB ให้เห็นข้อมูลจริง**

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

Expected: ต้องผ่านครบทุกข้อ ถ้าข้อใดข้อหนึ่งไม่ผ่านคืองานยังไม่เสร็จ

1. มีแถวข้อมูลกลับมา ไม่ว่าง
2. คอลัมน์ `_measurement` เป็น `traffic` ไม่ใช่ `mqtt_consumer`
3. มีคอลัมน์ `camera_id` ค่า `CAM_BUILDING2_FL02` และ `student_id` ค่า `6620301002`
4. มี `_field` ครบ 7 ตัว คือ `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`,
   `slow_vehicle_ratio`, `congestion_level`
5. คอลัมน์ `_time` ตรงกับ `timestamp` ที่จดไว้ใน Step 7 (คลาดได้ไม่เกิน 1 วินาที)
   ถ้าเวลาห่างเป็นสิบวินาทีแปลว่า `json_time_key` ไม่ทำงาน ให้กลับไปตรวจ Step 2

- [ ] **Step 9: Commit**

```bash
git add telegraf.conf docker-compose.yml mosquitto.conf
git commit -m "ให้ Telegraf เขียนข้อมูลจราจรเข้า InfluxDB กลาง

เดิม parser json ทิ้งค่า string ทุกตัวที่ไม่ได้ระบุใน tag_keys
ทำให้ camera_id หายไปทั้งหมดจนไม่รู้ว่าข้อมูลมาจากกล้องไหน
และเมื่อไม่ตั้ง json_time_key ข้อมูลจะถูกประทับเวลาที่ Telegraf รับข้อความ
แทนเวลาที่กล้องตรวจจับจริง ซึ่งใช้เทรนโมเดลทำนายไม่ได้

token อ่านจาก \${INFLUX_TOKEN} ที่ส่งเข้ามาทาง env_file ไม่ฝังในไฟล์
เอาต์พุต Kafka เดิมคงไว้ให้สายที่ 2 ใช้ต่อ"
```

---

### Task 4: เขียน README ใหม่พร้อม Flux query สำหรับ Grafana

Grafana เป็นของกลาง จึง provision จากฝั่งเราไม่ได้
งานส่งมอบคือ query ที่คัดลอกไปวางในหน้าสร้าง panel ได้ทันที

**Files:**
- Modify: `README.md`
- Delete: `detect_video.py`, `mqtt_publish.py` (ถูกลบจากดิสก์แล้ว เหลือแค่ commit การลบ)

**Interfaces:**
- Consumes: โครงสร้างข้อมูลใน InfluxDB จาก Task 3
- Produces: ไม่มี เป็น task สุดท้าย

- [ ] **Step 1: เขียน `README.md` ใหม่ทั้งไฟล์**

````markdown
# IOT_PROJECT — ตรวจจับสภาพจราจรจากวิดีโอ

ตรวจจับสภาพจราจรด้วย YOLO + ByteTrack แล้วส่งผลขึ้น MQTT
จากนั้น Telegraf กระจายข้อมูลออกสองทาง คือเข้า InfluxDB เพื่อดูบน Grafana
และเข้า Kafka เพื่อให้โมเดล ML ทำนายรถติดล่วงหน้า (ส่วนนี้ยังไม่ได้ทำ)

```
testmqtt.py (YOLO + ByteTrack)  ── JSON ทุก 10 วิ ──▶  Mosquitto (:1883)
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

`.env` ถูก gitignore ไว้แล้ว ห้าม commit ขึ้น repo เพราะ repo นี้เป็น public

## ใช้งาน

```bash
docker compose up -d          # Mosquitto, Kafka, Telegraf
python testmqtt.py test.mov   # กด q หรือ ESC เพื่อออก, space เพื่อหยุดชั่วคราว
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

### อาร์กิวเมนต์

| อาร์กิวเมนต์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `video` | `test.mov` | ไฟล์วิดีโอ, RTSP URL, หรือเลขกล้อง (`0` = webcam) |
| `--model` | `yolo26s.pt` | น้ำหนักโมเดล YOLO |
| `--roi` | `mapreal.png` | ภาพที่วาดขอบเขตถนนด้วยเส้นสีแดง (ใส่ `none` เพื่อตรวจทั้งเฟรม) |
| `--no-show` | – | ไม่เปิดหน้าต่างแสดงผล |

## payload ที่ส่งขึ้น MQTT

ส่งทุก 10 วินาที ไปที่ topic `traffic/6620301002`

```json
{
  "timestamp": "2026-09-09T14:30:00+07:00",
  "camera_id": "CAM_BUILDING2_FL02",
  "student_id": "6620301002",
  "car": 8,
  "motorcycle": 3,
  "bus": 0,
  "truck": 1,
  "vehicles_in_roi": 12,
  "slow_vehicle_ratio": 0.75,
  "congestion_level": 3
}
```

`congestion_level` คือ 0 = FREE, 1 = MODERATE, 2 = HEAVY, 3 = JAM

## โครงสร้างข้อมูลใน InfluxDB

| รายการ | ค่า |
|---|---|
| bucket | `mini_project` (ใช้ร่วมกันทั้งห้อง) |
| measurement | `traffic` |
| tags | `camera_id`, `student_id`, `topic` |
| fields | `car`, `motorcycle`, `bus`, `truck`, `vehicles_in_roi`, `slow_vehicle_ratio`, `congestion_level` |

field ทุกตัวเก็บเป็น float เพราะ parser `json` ของ Telegraf แปลงตัวเลขเป็น float ทั้งหมด

bucket นี้ใช้ร่วมกันทั้งห้อง ทุก query จึงต้องกรองด้วย `student_id` เสมอ
ไม่งั้นจะได้ข้อมูลของเพื่อนปนมาด้วย

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

เพิ่ม query ที่สองในหน้าเดียวกันเพื่อโชว์จำนวนรถ โดยเปลี่ยน `congestion_level`
เป็น `vehicles_in_roi`

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

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `testmqtt.py` | ตรวจจับ ติดตาม ตัดสินสภาพจราจร แล้วส่ง payload ขึ้น MQTT |
| `mapreal.png` | ภาพ ROI ที่วาดขอบเขตถนนด้วยเส้นสีแดง |
| `docker-compose.yml` | Mosquitto, Kafka, Telegraf |
| `telegraf.conf` | อ่าน MQTT แล้วกระจายเข้า InfluxDB และ Kafka |
| `mosquitto.conf` | config ของ MQTT broker |
| `.env` | token ของ InfluxDB (ไม่ขึ้น git) |

คลิปทดสอบ (`*.mp4`, `*.mov`) และน้ำหนักโมเดล (`*.pt`) ไม่ได้เก็บใน repo เพราะไฟล์ใหญ่

## เอกสารออกแบบ

`docs/superpowers/specs/` เก็บเหตุผลเบื้องหลังการตัดสินใจต่าง ๆ
โดยเฉพาะเรื่องโครงสร้างข้อมูลใน InfluxDB ที่แก้ย้อนหลังไม่ได้

## ยังไม่ได้ทำ

สาย Kafka ต่อไปยัง consumer ที่ใช้ Python ML ทำนายว่าอีกกี่นาทีข้างหน้ารถจะติด
ตอนนี้ข้อมูลไหลเข้า Kafka topic `traffic-events` แล้วแต่ยังไม่มีใครอ่าน
ต้องรอให้สะสมข้อมูลใน InfluxDB ระยะหนึ่งก่อนจึงจะมี training data พอ
````

- [ ] **Step 2: ตรวจว่า README ไม่ได้อ้างถึงไฟล์ที่ลบไปแล้ว**

```bash
grep -n "detect_video\|mqtt_publish\|ทุก 3 วิ\|1 นาที" README.md
```

Expected: ไม่พิมพ์อะไรเลย exit code 1
ถ้ายังเจอแปลว่าเขียนทับไม่ครบ ให้กลับไป Step 1

- [ ] **Step 3: Commit**

`detect_video.py` และ `mqtt_publish.py` ถูกลบจากดิสก์ไปแล้วแต่ยังอยู่ใน index
`git add -u` คือคำสั่งที่ stage การลบของไฟล์ที่ track อยู่แล้ว

```bash
git add README.md
git add -u detect_video.py mqtt_publish.py
git commit -m "เขียน README ใหม่ให้ตรงกับระบบปัจจุบัน

ของเดิมอธิบาย detect_video.py กับ mqtt_publish.py ซึ่งถูกแทนที่ด้วย testmqtt.py แล้ว
และระบุความถี่ผิดว่าส่งทุก 3 วินาทีแล้วสรุปรายนาที ของจริงคือ 10 วินาทีตลอดสาย

เพิ่ม Flux query ของทั้งสาม panel เพราะ Grafana เป็นของกลาง
เรา provision dashboard จากฝั่งนี้ไม่ได้ จึงส่งมอบเป็น query ให้คัดลอกไปวาง"
```

- [ ] **Step 4: ตรวจว่า working tree สะอาดและไม่มีอะไรหลุด**

```bash
git status --short
git log --oneline -5
```

Expected: `git status --short` ต้องไม่มี `.env` และไม่มี `test.mov`
เหลือได้เฉพาะไฟล์ที่ตั้งใจไม่ track เช่น `__pycache__` (ถูก ignore อยู่แล้ว)
และ `git log` ต้องเห็น 4 commit ใหม่ต่อจาก commit ของ spec

---

## การตรวจสอบขั้นสุดท้าย

ทำหลังจบ Task 4 ก่อนบอกผู้ใช้ว่าเสร็จ ห้ามข้าม

- [ ] **ตรวจว่า token ไม่เคยหลุดเข้า git ตลอดประวัติ branch นี้**

อ่านค่าจาก `.env` มาค้นแทนการพิมพ์ token ลงในคำสั่ง เพื่อไม่ให้ token
ไปโผล่ในไฟล์แผนหรือใน shell history

```bash
git log -p --all -S "$(cut -d= -f2- .env)" --oneline | head
```

Expected: ไม่พิมพ์อะไรเลย ถ้ามีผลลัพธ์แปลว่า token หลุดเข้า commit แล้ว
ต้องแจ้งผู้ใช้ทันทีให้ขอ token ใหม่จากอาจารย์ และห้าม push

- [ ] **ตรวจว่าไม่มีไฟล์ขนาดใหญ่หลุดเข้า git**

```bash
git ls-files | xargs -I{} du -k {} 2>/dev/null | sort -rn | head -5
```

Expected: ไฟล์ใหญ่สุดคือ `mapreal.png` ราว 770 KB ต้องไม่เห็น `test.mov`

- [ ] **ตรวจว่าข้อมูลไหลถึงปลายทางจริงและต่อเนื่อง**

รัน `python3 testmqtt.py test.mov --no-show` ทิ้งไว้ราว 1 นาที แล้ว query

```bash
set -a && . ./.env && set +a
curl -s -XPOST "http://172.16.2.117:8086/api/v2/query?org=my-org" \
  -H "Authorization: Token $INFLUX_TOKEN" \
  -H "Content-Type: application/vnd.flux" \
  -H "Accept: application/csv" \
  -d 'from(bucket:"mini_project")
      |> range(start: -10m)
      |> filter(fn: (r) => r._measurement == "traffic" and r.student_id == "6620301002")
      |> filter(fn: (r) => r._field == "congestion_level")'
```

Expected: ได้หลายแถวห่างกันราว 10 วินาที ไม่มีแถวไหนที่ค่าเป็นค่าว่าง
แสดงผลลัพธ์นี้ให้ผู้ใช้ดูเป็นหลักฐานว่าทำงานได้จริง

- [ ] **แจ้งผู้ใช้ว่าเสร็จ พร้อมบอกว่าต้องไปสร้าง panel เองบน Grafana กลาง**

---

## สิ่งที่จงใจไม่ทำในแผนนี้

- ไม่รัน InfluxDB หรือ Grafana ในเครื่อง ใช้ของกลางอย่างเดียวตามที่ตกลง
- ไม่แก้ `connect()` เป็น `connect_async` ใน `testmqtt.py` broker อยู่เครื่องเดียวกันและสั่ง `docker compose up -d` ก่อนอยู่แล้ว
- ไม่แตะสูตรตัดสินความติดขัด (`SLOW_VLPS`, `JAM_PERCENT`, `MIN_VEHICLES`) เป็นคนละเรื่องกับงานนี้
- ไม่รองรับหลายกล้อง `CAMERA_ID` ยังเป็นค่าคงที่ตัวเดียว
- ไม่ลง `pytest` ใช้ `python3 -c` และสคริปต์ชั่วคราวใน `/tmp` ตรวจแทน
- ไม่ทำ Kafka consumer และโมเดล ML เป็นสายที่ 2 ซึ่งจะ brainstorm แยกพร้อม spec ของตัวเอง
