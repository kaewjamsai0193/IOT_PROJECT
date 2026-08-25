# IOT_PROJECT — ตรวจจับสภาพจราจรจากวิดีโอ

ตรวจจับสภาพจราจรแบบเรียลไทม์ด้วย YOLOv8 + ByteTrack แล้วส่งผลขึ้น MQTT

วัดสองอย่างที่ต่างกันคนละเรื่อง

| ค่า | ความหมาย |
|---|---|
| `throughput` | จำนวนรถที่ข้ามเส้นนับ (ปริมาณรถที่ไหลผ่าน) |
| `congestion` | ความติดขัด วัดจากความหนาแน่นและความเร็วของรถใน ROI |

`throughput` บอกความติดขัดไม่ได้ เพราะเวลารถติดจริงรถจะข้ามเส้นน้อยลง
การแจ้งเตือนรถติดจึงใช้ `congestion` เท่านั้น

## ติดตั้ง

```bash
pip install ultralytics opencv-python numpy paho-mqtt
```

น้ำหนักโมเดล (`yolov8s.pt`) ไม่ได้อยู่ใน repo — ultralytics จะโหลดให้เองตอนรันครั้งแรก

## ใช้งาน

ดูผลบนหน้าต่างแสดงผล (`q` / `ESC` = ออก, `space` = หยุดชั่วคราว)

```bash
python detect_video.py videotest.mp4
```

ส่งขึ้น MQTT broker

```bash
python detect_video.py jam.mp4 --no-show | python mqtt_publish.py --host 192.168.1.10
```

ดูว่าจะส่งอะไรบ้างโดยไม่ต้องต่อ broker จริง

```bash
python detect_video.py jam.mp4 --no-show | python mqtt_publish.py --dry-run
```

### อาร์กิวเมนต์ `detect_video.py`

| อาร์กิวเมนต์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `video` | `videotest.mp4` | ไฟล์วิดีโอ, RTSP URL, หรือเลขกล้อง (`0` = webcam) |
| `--model` | `yolov8s.pt` | น้ำหนักโมเดล YOLO |
| `--roi` | `mapreal.png` | ภาพที่วาดขอบเขตด้วยเส้นสีแดง (ใส่ `none` เพื่อตรวจทั้งเฟรม) |
| `--no-show` | – | ไม่ต้องเปิดหน้าต่างแสดงผล |

### อาร์กิวเมนต์ `mqtt_publish.py`

| อาร์กิวเมนต์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `--host` | `localhost` | ที่อยู่ MQTT broker/gateway |
| `--port` | `1883` | พอร์ต broker |
| `--topic` | `traffic/<camera_id>` | อ่าน camera_id จาก payload |
| `--username` / `--password` | – | ข้อมูลยืนยันตัวตนของ broker |
| `--client-id` | `traffic-detector` | client id ของ MQTT |
| `--keepalive` | `60` | keepalive (วินาที) |
| `--dry-run` | – | แสดงสิ่งที่จะส่งโดยไม่ต่อ broker จริง |

เหตุการณ์รถติด (`TRAFFIC_JAM_ALERT`, `TRAFFIC_JAM_CLEARED`) ส่งแบบ QoS 1
ส่วนรายงานสถานะตามรอบส่ง QoS 0 เพราะตกไปบ้างไม่เป็นไร อีก 10 วินาทีก็ส่งใหม่

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `detect_video.py` | ตรวจจับ ติดตาม และตัดสินสภาพจราจร พิมพ์ payload JSON ออก stdout |
| `mqtt_publish.py` | อ่าน payload จาก stdin แล้วส่งขึ้น MQTT broker |
| `mapreal.png` | ภาพ ROI ที่วาดขอบเขตถนนด้วยเส้นสีแดง |

แยกการตรวจจับกับการส่ง MQTT เป็นคนละโปรเซส เพื่อให้การตรวจจับไม่สะดุดเวลา gateway ล่มหรือเน็ตหลุด

คลิปทดสอบ (`*.mp4`) และน้ำหนักโมเดล (`*.pt`) ไม่ได้เก็บใน repo เพราะไฟล์ใหญ่
