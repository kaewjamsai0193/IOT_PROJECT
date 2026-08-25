"""ตรวจจับสภาพจราจรจากวิดีโอแบบเรียลไทม์ด้วย YOLOv8 + ByteTrack

วัดสองอย่างที่ต่างกันคนละเรื่อง
  1. throughput  = จำนวนรถที่ข้ามเส้นนับ (ปริมาณรถที่ไหลผ่าน)
  2. congestion  = ความติดขัด วัดจากความหนาแน่นและความเร็วของรถใน ROI

ข้อควรรู้: throughput บอกความติดขัดไม่ได้ เพราะเวลารถติดจริงรถจะข้ามเส้นน้อยลง
การแจ้งเตือนรถติดจึงใช้ congestion เท่านั้น

  q / ESC = ออก, space = หยุดชั่วคราว
"""

import argparse
import collections
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CONF_THRESHOLD = 0.30
MAX_BOX_AREA_RATIO = 0.25  # รถคันเดียวไม่ควรกินพื้นที่เกิน 25% ของเฟรม CCTV
MIN_TRACK_AGE = 2          # ต้องเห็น track อย่างน้อยกี่ครั้งก่อนเชื่อค่าความเร็ว
SPEED_EMA = 0.6            # น้ำหนักค่าเก่าในการเฉลี่ยแบบ EMA ลด jitter ของกล่อง

# --- ค่าปรับแต่ง (เดิมเป็นอาร์กิวเมนต์ CLI ย้ายมาเป็นค่าคงที่เพื่อลดความยาว) ---
IMGSZ = 960          # ความละเอียดที่ป้อนเข้าโมเดล ยิ่งสูงยิ่งจับรถไกลได้ดีแต่ช้าลง
STRIDE = 2           # ตรวจจับทุกๆ N เฟรม
TRACKER = "bytetrack.yaml"
# ตำแหน่งเส้นนับ เทียบเป็นสัดส่วนความสูงเฟรม สวีป 0.70-0.86 กับ videotest+jam แล้ว
# ยอดนับไม่มีจุดพีคชัด (รวม 97-104) แต่ช่วง 0.76-0.80 เป็นย่านเดียวที่ยอดนิ่งทั้งสองคลิป
# นอกย่านนี้ยอดแกว่ง ±3-5 คันจาก track ID ที่หลุด/สลับ จึงเลือก 0.78 ซึ่งอยู่กลางย่าน
LINE_RATIO = 0.78
SLOW_VLPS = 0.30     # ความเร็วต่ำกว่านี้ถือว่ารถเคลื่อนช้า (ความยาวรถ/วินาที)
JAM_PERCENT = 55.0   # แจ้งเตือนเมื่อรถช้าเกินกี่ % ของรถใน ROI
MIN_VEHICLES = 4     # ต้องมีรถใน ROI อย่างน้อยกี่คันจึงจะตัดสินว่าติด
WINDOW_SEC = 5.0     # เฉลี่ยค่าย้อนหลังกี่วินาที กันสถานะแกว่ง
INTERVAL_SEC = 10.0  # พิมพ์ payload ทุกกี่วินาทีของวิดีโอ
REALTIME = True      # หน่วงให้หน้าต่างแสดงผลเล่นเท่าความเร็ววิดีโอจริง (ไม่มีผลกับ --no-show)

# เกณฑ์ระดับความติดขัด หน่วยเป็น % ของรถที่เคลื่อนช้ากว่า SLOW_VLPS
# ค่าเหล่านี้ได้จากการวัด videotest.mp4 จริง (ช่วงโล่ง 6-11%, ช่วงติด 46-62%)
LEVELS = [(20, "FREE"), (35, "MODERATE"), (55, "HEAVY"), (101, "JAM")]

COLOR_LINE = (255, 0, 0)
COLOR_ROI = (0, 0, 255)
COLOR_NEW = (0, 255, 0)
COLOR_COUNTED = (0, 200, 255)
LEVEL_COLORS = {
    "FREE": (0, 200, 0), "MODERATE": (0, 220, 220), "HEAVY": (0, 140, 255),
    "JAM": (0, 0, 255), "UNKNOWN": (160, 160, 160),
}


def load_roi_mask(mask_path: Path, width: int, height: int) -> np.ndarray:
    """สร้าง ROI mask จากภาพที่วาดเส้นขอบสีแดงไว้ (255 = พื้นที่ที่สนใจ)"""
    img = cv2.imread(str(mask_path))
    if img is None:
        raise FileNotFoundError(f"เปิดไฟล์ ROI ไม่ได้: {mask_path}")

    b, g, r = cv2.split(img.astype(np.int16))
    red = ((r > 120) & (r - g > 60) & (r - b > 60)).astype(np.uint8) * 255
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    if not red.any():
        raise ValueError(f"ไม่พบเส้นขอบสีแดงใน {mask_path}")

    # เติมสีจากนอกกรอบเข้ามา พิกเซลที่เติมไม่ถึง = ด้านในกรอบ
    h, w = red.shape
    padded = cv2.copyMakeBorder(red, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    cv2.floodFill(padded, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 255)
    filled = np.where((padded[1:-1, 1:-1] == 0) | (red > 0), 255, 0).astype(np.uint8)

    # เก็บเฉพาะก้อนที่ใหญ่ที่สุด กันวัตถุสีแดงอื่นในภาพปนเข้ามา
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(filled, 8)
    if n_labels > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        filled = np.where(labels == largest, 255, 0).astype(np.uint8)

    if filled.shape != (height, width):
        filled = cv2.resize(filled, (width, height), interpolation=cv2.INTER_NEAREST)
    return filled


class CongestionMonitor:
    """ประเมินความติดขัดจากความหนาแน่นและความเร็วของรถใน ROI

    ความเร็ววัดเป็น "ความยาวรถต่อวินาที" (ระยะที่เคลื่อน / ความสูงกล่องของคันนั้น)
    ทำให้เทียบรถใกล้กับรถไกลได้ทั้งที่กล้องมองมุมสูง
    """

    def __init__(self, fps: float, sample_rate: float, hysteresis: float = 10.0):
        self.fps = fps
        self.hysteresis = hysteresis
        self.window = collections.deque(maxlen=max(1, int(WINDOW_SEC * sample_rate)))
        self.last_seen = {}     # tid -> (frame_idx, cx, cy)
        self.speed_ema = {}     # tid -> ความเร็วเฉลี่ยแบบ EMA
        self.hits = collections.Counter()
        self.alert_active = False

    def update_track(self, tid: int, frame_idx: int, cx: float, cy: float, box_h: float):
        """บันทึกตำแหน่งรถหนึ่งคัน แล้วคืนความเร็วปัจจุบัน (None ถ้ายังคำนวณไม่ได้)"""
        previous = self.last_seen.get(tid)
        self.last_seen[tid] = (frame_idx, cx, cy)
        self.hits[tid] += 1
        if previous is None:
            return None

        # หารด้วยจำนวนเฟรมที่ผ่านไปจริง รองรับการข้ามเฟรมและ track ที่หายกลางคัน
        dt = (frame_idx - previous[0]) / self.fps
        if dt <= 0 or box_h <= 0:
            return None

        vlps = math.hypot(cx - previous[1], cy - previous[2]) / box_h / dt
        smoothed = vlps if tid not in self.speed_ema else (
            SPEED_EMA * self.speed_ema[tid] + (1 - SPEED_EMA) * vlps)
        self.speed_ema[tid] = smoothed
        return smoothed if self.hits[tid] >= MIN_TRACK_AGE else None

    def commit_frame(self, n_vehicles: int, speeds: list):
        self.window.append((n_vehicles, speeds))

    def forget(self, tid: int):
        self.last_seen.pop(tid, None)
        self.speed_ema.pop(tid, None)
        self.hits.pop(tid, None)

    def stats(self) -> dict:
        if not self.window:
            return {"level": "UNKNOWN", "vehicles_in_roi": 0.0,
                    "mean_speed_vlps": 0.0, "stopped_percent": 0.0, "alert": False}

        counts = [n for n, _ in self.window]
        speeds = [v for _, sp in self.window for v in sp]
        mean_n = sum(counts) / len(counts)
        stopped_pct = (sum(1 for v in speeds if v < SLOW_VLPS) / len(speeds) * 100
                       if speeds else 0.0)
        mean_speed = sum(speeds) / len(speeds) if speeds else 0.0

        # ถนนโล่งที่มีรถจอดคันเดียวจะได้ 100% ต้องมีรถมากพอก่อนจึงตัดสิน
        if mean_n < MIN_VEHICLES:
            level = "FREE" if speeds else "UNKNOWN"
        else:
            level = next(name for limit, name in LEVELS if stopped_pct < limit)

        # ใส่ hysteresis กันสถานะกระพริบไปมาตรงเส้นแบ่ง
        # และห้ามเริ่มเตือนจนกว่าหน้าต่างจะมีข้อมูลเกินครึ่ง ไม่งั้นตอนสตาร์ทระบบ
        # ความเร็วยังคำนวณไม่ได้ ทุกคันดูเหมือนจอดนิ่ง เลยยิงเตือนหลอกทันทีทุกครั้ง
        enough = mean_n >= MIN_VEHICLES
        warm = len(self.window) >= self.window.maxlen // 2
        if self.alert_active:
            if not enough or stopped_pct < JAM_PERCENT - self.hysteresis:
                self.alert_active = False
        elif warm and enough and stopped_pct >= JAM_PERCENT:
            self.alert_active = True

        return {
            "level": level,
            "vehicles_in_roi": round(mean_n, 1),
            "mean_speed_vlps": round(mean_speed, 2),
            "stopped_percent": round(stopped_pct, 1),
            "alert": self.alert_active,
        }


def build_payload(counts: dict, directions: dict, congestion: dict, roi_now: dict,
                  elapsed_sec: float, event: str = "TRAFFIC_STATUS") -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": "CAM_BUILDING2_FL02",
        "event_type": event,
        "video_time_sec": round(elapsed_sec, 1),
        # ยอดสะสมของรถที่ไหลผ่านเส้นนับ ไม่ใช่ตัวบอกความติดขัด
        "throughput": {**counts, "total_vehicles": sum(counts.values()),
                       "by_direction": dict(directions)},
        # ความติดขัด ใช้ตัวนี้ในการแจ้งเตือน (mean_speed_vlps ตัดออก เหลือแค่บน HUD)
        "congestion": {
            **{k: congestion[k] for k in
               ("level", "vehicles_in_roi", "stopped_percent", "alert")},
            # จำนวนรถที่ค้างอยู่ใน ROI ณ วินาทีนั้นจริงๆ ต่างจาก vehicles_in_roi
            # ที่เป็นค่าเฉลี่ยย้อนหลัง WINDOW_SEC วินาที (ตัวที่ใช้ตัดสินระดับ)
            "vehicles_now": {**{name: roi_now.get(name, 0) for name in CLASS_NAMES.values()},
                             "total": sum(roi_now.values())},
        },
    }


def draw_hud(frame, counts, congestion, fps_live, line_span, roi_contours) -> None:
    """วาดกรอบ ROI เส้นนับ และแผงตัวเลข (ข้อความเป็น ASCII เพราะ cv2 วาดไทยไม่ได้)"""
    if roi_contours is not None:
        cv2.drawContours(frame, roi_contours, -1, COLOR_ROI, 2)

    (lx1, ly), (lx2, _) = line_span
    cv2.line(frame, (lx1, ly), (lx2, ly), COLOR_LINE, 2)
    cv2.putText(frame, "COUNT LINE", (lx1 + 4, ly - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_LINE, 1, cv2.LINE_AA)

    level = congestion["level"]
    color = LEVEL_COLORS.get(level, LEVEL_COLORS["UNKNOWN"])
    lines = [
        ("TRAFFIC: {}".format(level), color),
        ("slow {:.0f}%  in-roi {:.1f}".format(
            congestion["stopped_percent"], congestion["vehicles_in_roi"]), (255, 255, 255)),
        ("speed {:.2f} veh-len/s".format(congestion["mean_speed_vlps"]), (255, 255, 255)),
        ("crossed {}  ({:.1f} fps)".format(sum(counts.values()), fps_live), (200, 200, 200)),
    ]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (250, 18 * len(lines) + 14), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    for i, (text, col) in enumerate(lines):
        cv2.putText(frame, text, (8, 22 + i * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

    if congestion["alert"]:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 4)
        cv2.putText(frame, "!! TRAFFIC JAM !!", (w // 2 - 130, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="ตรวจจับสภาพจราจรจากวิดีโอแบบเรียลไทม์")
    parser.add_argument("video", nargs="?", default="videotest.mp4",
                        help="ไฟล์วิดีโอ, RTSP URL, หรือเลขกล้อง (0 = webcam)")
    parser.add_argument("--model", default="yolov8s.pt")
    parser.add_argument("--roi", default="mapreal.png",
                        help="ภาพที่วาดขอบเขตด้วยเส้นสีแดง (ใส่ none เพื่อตรวจทั้งเฟรม)")
    parser.add_argument("--no-show", action="store_true", help="ไม่ต้องเปิดหน้าต่างแสดงผล")
    args = parser.parse_args()

    # ให้พิมพ์ภาษาไทยบน console Windows ได้โดยไม่ต้องตั้ง PYTHONIOENCODING
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    source = int(args.video) if args.video.isdigit() else args.video
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        sys.exit("เปิดวิดีโอไม่ได้: {}".format(args.video))

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_area = width * height
    line_y = int(height * LINE_RATIO)
    interval_frames = max(1, int(fps * INTERVAL_SEC))

    roi_mask = None
    roi_contours = None
    if args.roi and args.roi.lower() != "none":
        roi_mask = load_roi_mask(Path(args.roi), width, height)
        roi_contours, _ = cv2.findContours(roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        print("ROI: {} ครอบคลุม {:.1f}% ของเฟรม".format(args.roi, (roi_mask > 0).mean() * 100),
              file=sys.stderr)

    # ครอปเฉพาะกรอบสี่เหลี่ยมที่ล้อม ROI ก่อนป้อนเข้าโมเดล
    # ได้ทั้งความเร็ว (พิกเซลน้อยลง) และความละเอียดต่อคันที่สูงขึ้น
    if roi_mask is not None:
        ys, xs = np.nonzero(roi_mask)
        cx1, cx2 = int(xs.min()), int(xs.max()) + 1
        cy1, cy2 = int(ys.min()), int(ys.max()) + 1
    else:
        cx1, cy1, cx2, cy2 = 0, 0, width, height

    # ช่วงของเส้นนับที่พาดผ่าน ROI จริง ใช้ทั้งวาดและอธิบายขอบเขตการนับ
    if roi_mask is not None and 0 <= line_y < height and (roi_mask[line_y] > 0).any():
        inside = np.flatnonzero(roi_mask[line_y] > 0)
        line_span = ((int(inside[0]), line_y), (int(inside[-1]), line_y))
    else:
        line_span = ((0, line_y), (width, line_y))

    print("video: {}x{} @ {:.1f}fps | LINE_Y={} | imgsz={} | stride={}".format(
        width, height, fps, line_y, IMGSZ, STRIDE), file=sys.stderr)
    show = not args.no_show
    if show:
        print("กด q หรือ ESC เพื่อออก, space เพื่อหยุดชั่วคราว", file=sys.stderr)

    model = YOLO(args.model)
    monitor = CongestionMonitor(fps, fps / STRIDE)

    counts = {name: 0 for name in CLASS_NAMES.values()}
    directions = {"up": 0, "down": 0}
    prev_center_y = {}   # track_id -> center_y ของเฟรมที่ตรวจจับครั้งก่อน
    # YOLO สลับคลาสไปมาระหว่างเฟรม (car/truck) จึงเก็บสถิติไว้โหวตตอนนับ
    class_votes = collections.defaultdict(collections.Counter)
    counted_ids = set()
    congestion = monitor.stats()
    roi_now = collections.Counter()   # กันพังกรณีคลิปจบก่อนวนลูปได้สักรอบ
    was_alerting = False
    frame_idx = 0
    paused = False
    fps_live = 0.0
    freq = cv2.getTickFrequency()
    start_tick = cv2.getTickCount()   # จุดอ้างอิงเวลาจริง ใช้เทียบกับเวลาในวิดีโอ
    tick = start_tick

    while True:
        if paused:
            pause_tick = cv2.getTickCount()
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = False
            # เลื่อนจุดอ้างอิงตามเวลาที่หยุดไป ไม่งั้นพอเล่นต่อจะรีบไล่เฟรมให้ทัน
            start_tick += cv2.getTickCount() - pause_tick
            continue

        tick = cv2.getTickCount()

        # ข้ามเฟรมด้วย grab() ซึ่งถอดรหัสภาพไม่เต็มรูปแบบ จึงถูกกว่า read()
        ended = False
        for _ in range(STRIDE - 1):
            if not cap.grab():
                ended = True
                break
            frame_idx += 1
        if ended:
            break

        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        results = model.track(
            frame[cy1:cy2, cx1:cx2], persist=True, tracker=TRACKER, imgsz=IMGSZ,
            classes=list(CLASS_NAMES.keys()), conf=CONF_THRESHOLD, verbose=False)

        boxes = results[0].boxes
        seen_ids = set()
        frame_speeds = []
        n_in_roi = 0
        roi_now = collections.Counter()   # รถใน ROI ณ เฟรมนี้ แยกตามประเภท

        if boxes is not None and boxes.id is not None:
            xyxy = boxes.xyxy.cpu().numpy()
            track_ids = boxes.id.int().cpu().numpy()
            cls_ids = boxes.cls.int().cpu().numpy()

            for box, track_id, cls_id in zip(xyxy, track_ids, cls_ids):
                # พิกัดอยู่ในระบบของภาพที่ครอป ต้องบวกออฟเซ็ตกลับเป็นพิกัดเฟรมเต็ม
                x1, y1 = int(box[0]) + cx1, int(box[1]) + cy1
                x2, y2 = int(box[2]) + cx1, int(box[3]) + cy1

                if (x2 - x1) * (y2 - y1) > frame_area * MAX_BOX_AREA_RATIO:
                    continue
                vehicle_type = CLASS_NAMES.get(int(cls_id))
                if vehicle_type is None:
                    continue

                # จุดอ้างอิง = กึ่งกลางขอบล่างของกรอบ คือจุดที่รถแตะพื้นถนน
                anchor_x = min(max((x1 + x2) // 2, 0), width - 1)
                anchor_y = min(max(y2, 0), height - 1)
                if roi_mask is not None and roi_mask[anchor_y, anchor_x] == 0:
                    continue

                tid = int(track_id)
                seen_ids.add(tid)
                n_in_roi += 1
                center_y = (y1 + y2) // 2
                class_votes[tid][vehicle_type] += 1
                # ใช้คลาสที่โหวตแล้วเหมือนตอนนับข้ามเส้น ไม่ให้ประเภทกระพริบไปมา
                roi_now[class_votes[tid].most_common(1)[0][0]] += 1

                speed = monitor.update_track(tid, frame_idx, (x1 + x2) / 2,
                                             (y1 + y2) / 2, y2 - y1)
                if speed is not None:
                    frame_speeds.append(speed)

                # นับ throughput เมื่อ "ตัดผ่าน" เส้นจริง รับทั้งสองทิศทาง
                previous = prev_center_y.get(tid)
                prev_center_y[tid] = center_y
                direction = None
                if previous is not None:
                    if previous < line_y <= center_y:
                        direction = "down"
                    elif previous >= line_y > center_y:
                        direction = "up"

                if direction and tid not in counted_ids:
                    counted_ids.add(tid)
                    # ใช้คลาสที่พบบ่อยที่สุดตลอด track ไม่ใช่คลาสของเฟรมที่ตัดผ่าน
                    voted_type = class_votes[tid].most_common(1)[0][0]
                    counts[voted_type] += 1
                    directions[direction] += 1

                if show:
                    color = COLOR_COUNTED if tid in counted_ids else COLOR_NEW
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    label = "{}#{}".format(vehicle_type, tid)
                    if speed is not None:
                        label += " {:.1f}".format(speed)
                    cv2.putText(frame, label, (x1, max(y1 - 6, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        monitor.commit_frame(n_in_roi, frame_speeds)
        congestion = monitor.stats()

        # ลบ track ที่หายไปแล้ว กัน dict โตไม่มีขอบเขต
        for stale in prev_center_y.keys() - seen_ids:
            del prev_center_y[stale]
            class_votes.pop(stale, None)
            monitor.forget(stale)

        # วัดความเร็วประมวลผลจริง ไม่รวมเวลาที่หน่วงรอให้ตรงกับวิดีโอ
        fps_live = freq / max(cv2.getTickCount() - tick, 1)

        # แจ้งเตือนทันทีที่สถานะเปลี่ยน ไม่ต้องรอรอบ payload ปกติ
        if congestion["alert"] != was_alerting:
            was_alerting = congestion["alert"]
            event = "TRAFFIC_JAM_ALERT" if was_alerting else "TRAFFIC_JAM_CLEARED"
            print("[{}] t={:.1f}s รถช้า {:.0f}% รถใน ROI {:.1f} คัน".format(
                event, frame_idx / fps, congestion["stopped_percent"],
                congestion["vehicles_in_roi"]), file=sys.stderr)
            print(json.dumps(build_payload(counts, directions, congestion, roi_now,
                                           frame_idx / fps, event),
                             indent=2, ensure_ascii=False), flush=True)

        if frame_idx % interval_frames < STRIDE:
            print(json.dumps(build_payload(counts, directions, congestion, roi_now,
                                           frame_idx / fps),
                             indent=2, ensure_ascii=False), flush=True)

        if show:
            draw_hud(frame, counts, congestion, fps_live, line_span, roi_contours)
            cv2.imshow("Traffic Monitor", frame)

            # หน่วงจนเวลาที่ผ่านไปจริงเท่ากับเวลาในวิดีโอ ไม่งั้นเครื่องเร็วจะเล่นเร็วเกิน
            wait_ms = 1
            if REALTIME:
                behind_sec = frame_idx / fps - (cv2.getTickCount() - start_tick) / freq
                if behind_sec < -1.0:
                    # ตามหลังเกิน 1 วิ (เช่น ตอนอุ่นเครื่องโมเดล) ตั้งจุดอ้างอิงใหม่
                    # ไม่ให้ไล่เฟรมรวดเดียวจนภาพกระตุก
                    start_tick = cv2.getTickCount() - int(frame_idx / fps * freq)
                else:
                    wait_ms = max(1, int(behind_sec * 1000))
            key = cv2.waitKey(wait_ms) & 0xFF
            if key in (ord("q"), 27):
                print("ผู้ใช้กดออก", file=sys.stderr)
                break
            if key == ord(" "):
                paused = True

    # payload ปิดท้ายเสมอ แม้คลิปจบก่อนครบรอบ
    print("=== FINAL ===", file=sys.stderr)
    print(json.dumps(build_payload(counts, directions, congestion, roi_now, frame_idx / fps),
                     indent=2, ensure_ascii=False), flush=True)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
