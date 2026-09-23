# แดชบอร์ดบน Grafana

กลับไปหน้าแรก [README](../README.md)

## Dashboard บน Grafana

สร้าง panel แล้วเลือก datasource เป็น InfluxDB ที่ชี้ไป bucket `mini_project`
จากนั้นคัดลอก query ข้างล่างไปวาง

### สีให้ตรงกันทุก panel

กฎข้อเดียวที่ทำให้ทั้งแดชบอร์ดอ่านง่าย คือ **สงวนสีไฟจราจรสี่สีไว้ให้ "ระดับ" เท่านั้น**
อะไรที่เป็นจำนวนรถให้ใช้สีคนละตระกูล (ฟ้า/ม่วง) จะได้ไม่มีวันขัดกันเอง
เพราะจำนวนรถมากไม่ได้แปลว่ารถติด ตัวตัดสินระดับคือ `slow_vehicle_ratio` ไม่ใช่จำนวนรถ

| ใช้กับ | ค่า | สี | hex |
|---|---|---|---|
| ระดับ | 0 FREE | เขียว | `#73BF69` |
| ระดับ | 1 MODERATE | เหลือง | `#EAB839` |
| ระดับ | 2 HEAVY | ส้ม | `#FFB357` |
| ระดับ | 3 JAM | แดง | `#E24D42` |
| จำนวนรถ | – | ฟ้า | `#5794F2` |
| รถแยกชนิด | car / motorcycle / bus / truck | ฟ้า-ม่วง | `#5794F2` `#B877D9` `#64B0C8` `#8AB8FF` |

ชุดนี้ตรงกับภาพร่างแดชบอร์ดใน `docs/grafana-dashboard-layout.svg`

#### ชุด mapping ที่ใช้ได้ทั้งค่าจริงและค่าพยากรณ์

`congestion_level` ที่วัดได้เป็นจำนวนเต็ม แต่ `forecast_congestion_level` เป็นทศนิยม
ถ้าใช้ Value mapping แบบจับค่าตรงตัว (`0`, `1`, `2`, `3`) panel พยากรณ์จะไม่ติดสีเลย
เพราะ `1.53` ไม่ตรงกับค่าไหน ใช้ **Range mapping** ชุดเดียวครอบคลุมทั้งสองแบบแทน

เปิด panel แล้วกด **Edit → ปุ่ม JSON (Panel JSON)** วางลงใน `fieldConfig.defaults`

```json
"color": { "mode": "thresholds" },
"mappings": [
  {"type":"range","options":{"from":0,"to":0.5,"result":{"text":"FREE","color":"#73BF69","index":0}}},
  {"type":"range","options":{"from":0.5,"to":1.5,"result":{"text":"MODERATE","color":"#EAB839","index":1}}},
  {"type":"range","options":{"from":1.5,"to":2.5,"result":{"text":"HEAVY","color":"#FFB357","index":2}}},
  {"type":"range","options":{"from":2.5,"to":3,"result":{"text":"JAM","color":"#E24D42","index":3}}}
],
"thresholds": {
  "mode": "absolute",
  "steps": [
    {"color":"#73BF69","value":null},
    {"color":"#EAB839","value":0.5},
    {"color":"#FFB357","value":1.5},
    {"color":"#E24D42","value":2.5}
  ]
}
```

สองเรื่องที่พลาดกันบ่อย

- ต้องมี `"color": {"mode": "thresholds"}` ด้วย ถ้าเป็น `palette-classic` Grafana จะแจกสี
  ตามลำดับ series แล้วสีใน mapping จะไม่ถูกใช้เลย
- ช่วงของ range mapping ชนกันที่หัวท้าย (`0.5` อยู่ทั้งช่วงแรกและช่วงสอง)
  Grafana ใช้ตัวที่เจอก่อน เรียงตาม `index` จึงต้องเรียงจากน้อยไปมากเสมอ

`mappings` ทำให้ Stat กับ State timeline ได้สีตรงกัน ส่วน `thresholds` ทำให้เส้นกราฟ
Time series (ค่าจริงเทียบค่าพยากรณ์) เปลี่ยนสีตามระดับเดียวกัน ใส่ทั้งสองชุดไปเลย
ชุดไหนไม่ถูกใช้ก็ไม่เสียหาย

คัดลอกไปวางให้ครบทุก panel ที่แสดงระดับ ทั้ง `congestion_level`,
`forecast_congestion_level` และ `forecast_level_rounded`

#### จำนวนรถทั้งหมด

`vehicles_in_roi` เป็นคนละหน่วยกับระดับ อย่ายืม threshold ของระดับมาใช้
ไม่งั้นจะเจอกรณีรถ 15 คันวิ่งฉิวแล้ว tile ขึ้นสีแดงทั้งที่ระดับเป็น FREE ซึ่งขัดกันเอง

ตั้งเป็นสีเดียวไปเลย ใน panel เดียวกับระดับให้ใส่ override เฉพาะ field นี้

```json
"overrides": [
  {
    "matcher": {"id":"byName","options":"vehicles_in_roi"},
    "properties": [
      {"id":"color","value":{"mode":"fixed","fixedColor":"#5794F2"}},
      {"id":"mappings","value":[]}
    ]
  }
]
```

ได้ผลเป็น tile ซ้ายบอกสถานะด้วยสีไฟจราจร tile ขวาบอกจำนวนด้วยสีฟ้านิ่ง ๆ
คนอ่านรู้ทันทีว่าสีที่ต้องดูคือตัวซ้าย

ถ้าอยากได้ threshold บนจำนวนรถจริง ๆ มีเส้นเดียวที่มีความหมายตามโค้ด คือ `4`
(`MIN_VEHICLES` ใน `testmqtt.py`) ต่ำกว่านี้โค้ดบังคับระดับเป็น 0 เสมอไม่ว่ารถจะช้าแค่ไหน

#### วัดแล้วว่าสีตามจำนวนรถไม่มีทางตรงกับระดับ

วัดจากข้อมูลจริง 896 จุดใน bucket (2026-09-09 ถึง 2026-09-23)
จำนวนรถในแต่ละระดับซ้อนทับกันเยอะมาก

| ระดับ | จำนวนจุด | รถน้อยสุด | กลาง | มากสุด |
|---|---|---|---|---|
| 0 FREE | 530 | 5 | 8 | 13 |
| 1 MODERATE | 115 | 7 | 9 | 14 |
| 2 HEAVY | 111 | 9 | 12 | 16 |
| 3 JAM | 140 | 11 | 15 | 20 |

รถ 12 คันเป็นได้ทั้ง FREE และ JAM เพราะตัวตัดสินคือรถช้ากี่เปอร์เซ็นต์ ไม่ใช่มีรถกี่คัน
ลองไล่หาเส้นแบ่งทุกแบบที่เป็นไปได้แล้ว **ดีที่สุดคือ `[0-10] [11-12] [13] [14+]` ตรงกัน 73%**
ยังผิดหนึ่งในสี่ครั้งอยู่ดี ส่วนเส้นแบ่งแบบแบ่งเท่า ๆ กันอย่าง `[0-7] [8-10] [11-14] [15-20]`
ตรงแค่ 46% คือครั้งที่ระดับเป็น FREE แต่ tile ขึ้นสีเหลืองมีถึง 268 ครั้ง

จะฝืนใช้ก็ได้ถ้ารู้ตัวว่ามันคือ "สีของจำนวนรถ" ไม่ใช่ "สีของรถติด"
แต่อย่าลืมเปิดปลายบนทิ้งไว้ ช่วงสุดท้ายที่ปิดท้ายด้วย `20` จะทำให้รถ 21 คันขึ้นไปไม่มีสีเลย

#### อยากให้ tile จำนวนรถเปลี่ยนสีตามระดับจริง ๆ

ให้ดึงสีมาจาก `congestion_level` ตรง ๆ แทนการเดาจากจำนวนรถ จะตรงกัน 100% ตามนิยาม
เพิ่ม query ที่สองในหน้าเดียวกัน (ซ่อนไว้ กดรูปตา) ที่คืนค่าเป็น "สี" ไม่ใช่ตัวเลข

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic_6620301002")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "congestion_level")
  |> last()
  |> map(fn: (r) => ({
      _time: r._time,
      color:
        if r._value >= 2.5 then "#E24D42"
        else if r._value >= 1.5 then "#FFB357"
        else if r._value >= 0.5 then "#EAB839"
        else "#73BF69",
    }))
```

แล้วไปที่แท็บ **Transformations → Config from query results**
ตั้ง Config query เป็น query สีนี้ แล้ว map field `color` ไปที่ property **Color**
tile จำนวนรถจะรับสีจากระดับโดยไม่ต้องเดาเส้นแบ่งเอง

ถ้า Grafana รุ่นที่ใช้ไม่มี property `Color` ให้เลือก ก็กลับไปใช้สีฟ้านิ่ง ๆ
ซึ่งอ่านง่ายกว่าการเดาเส้นแบ่งที่ผิดหนึ่งในสี่ครั้งอยู่ดี

#### รถแยกชนิดใน Panel 2

ปล่อยให้ Grafana แจกสีเอง สีจะสลับกันเมื่อบางชนิดไม่มีข้อมูลในช่วงเวลาที่เลือก
เช่นช่วงที่ไม่มี `bus` เลย สีของ `truck` จะเลื่อนมากินสีเดิมของ `bus` ล็อกด้วย override

```json
{"matcher":{"id":"byName","options":"car"},        "properties":[{"id":"color","value":{"mode":"fixed","fixedColor":"#5794F2"}}]},
{"matcher":{"id":"byName","options":"motorcycle"}, "properties":[{"id":"color","value":{"mode":"fixed","fixedColor":"#B877D9"}}]},
{"matcher":{"id":"byName","options":"bus"},        "properties":[{"id":"color","value":{"mode":"fixed","fixedColor":"#64B0C8"}}]},
{"matcher":{"id":"byName","options":"truck"},      "properties":[{"id":"color","value":{"mode":"fixed","fixedColor":"#8AB8FF"}}]}
```

### Panel 1 — สถานะปัจจุบัน (Stat)

```flux
from(bucket: "mini_project")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "traffic_6620301002")
  |> filter(fn: (r) => r.student_id == "6620301002")
  |> filter(fn: (r) => r._field == "congestion_level")
  |> last()
```

ใส่ mapping กับ threshold ตามหัวข้อ [สีให้ตรงกันทุก panel](#สีให้ตรงกันทุก-panel)

อยากโชว์จำนวนรถคู่กัน ให้เพิ่ม query ที่สองในหน้าเดียวกัน
โดยเปลี่ยน `congestion_level` เป็น `vehicles_in_roi` แล้วใส่ override สีฟ้าให้ field นั้น
ไม่งั้นมันจะไปหยิบ mapping ของระดับมาใช้ กลายเป็นรถ 2 คันขึ้นคำว่า HEAVY

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

ใช้ `mappings` ชุดเดียวกับ Panel 1 คัดลอก JSON ไปวางทั้งก้อน อย่าไล่ตั้งทีละค่าในหน้า UI
เพราะพิมพ์ hex ผิดตัวเดียวสีสอง panel ก็เพี้ยนจากกันแล้ว
