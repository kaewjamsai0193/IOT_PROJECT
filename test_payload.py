"""ตรวจว่า payload ที่ส่งขึ้น MQTT ถูกต้อง รันด้วย python3 test_payload.py

สองเรื่องที่ต้องไม่พังเด็ดขาด เพราะ InfluxDB และโมเดล ML ปลายทางพึ่งมันอยู่
1. congestion_level ต้องเป็นตัวเลขเสมอ ไม่มี null ไม่งั้น Telegraf ทิ้งฟิลด์
   แล้ว time series จะขาดเป็นช่วง
2. ทุก payload ต้องมี student_id เพราะ bucket ใน InfluxDB ใช้ร่วมกันทั้งห้อง
   ถ้า tag ชนกัน InfluxDB จะเขียนทับกันเงียบ ๆ
"""

import testmqtt as t

EMPTY = {"counts": {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}, "occ": 0.0, "slow": 0.0}
BUSY = {"counts": {"car": 8, "motorcycle": 3, "bus": 0, "truck": 1}, "occ": 12.0, "slow": 0.9}

assert t.level_code(0.0, 0) == 0, "ถนนว่างคือถนนที่ไม่ติด ต้องเป็น FREE (0) ไม่ใช่ None"
assert t.level_code(0.0, 2) == 0, "รถน้อยกว่า MIN_VEHICLES ต้องเป็น FREE"
assert t.level_code(0.9, 10) == 3, "รถช้า 90% ต้องเป็น JAM (3)"

p = t.build_payload(EMPTY)
assert p["student_id"] == "6620301002", "payload ต้องมี student_id"
assert p["congestion_level"] == 0, "ตอนไม่มีรถ congestion_level ต้องเป็น 0 ไม่ใช่ None"

q = t.build_payload(BUSY)
assert q["congestion_level"] == 3
assert q["camera_id"] == "CAM_BUILDING2_FL02"
assert q["vehicles_in_roi"] == 12
assert None not in q.values(), "ห้ามมีค่า null ใน payload"

print("ผ่านทั้งหมด")
