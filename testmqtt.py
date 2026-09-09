from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt
import torch
from ultralytics import YOLO

CAMERA_ID = "CAM_BUILDING2_FL02"
STUDENT_ID = "6620301002"
CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CONF_THR = {2: 0.30, 3: 0.30, 5: 0.30, 7: 0.30}
MAX_BOX_AREA_RATIO = 0.25  # กล่องเดียวไม่ควรเกิน 25% ของเฟรม CCTV
TRACK_TTL_SEC = 0.25  # ลืม track เมื่อหายเกินนี้
SPEED_EMA = 0.6  # น้ำหนักค่าเก่าใน EMA ลด jitter ของกล่อง
IMGSZ, STRIDE, TRACKER = 960, 2, "bytetrack.yaml"
SLOW_VLPS = 0.30  # ต่ำกว่านี้ถือว่าช้า (ความยาวรถ/วินาที)
JAM_PERCENT, MIN_VEHICLES = 55.0, 4
WINDOW_SEC, INTERVAL_SEC, REALTIME = 5.0, 10, True
LEVELS = [(20, "FREE"), (35, "MODERATE"), (55, "HEAVY"), (101, "JAM")]
LEVEL_COLORS = {
    "FREE": (0, 200, 0),
    "MODERATE": (0, 220, 220),
    "HEAVY": (0, 140, 255),
    "JAM": (0, 0, 255),
    "UNKNOWN": (160, 160, 160),
}

# --- ตั้งค่า MQTT ---
MQTT_PORT = 1883

# broker ในเครื่อง เลี้ยง Telegraf ที่เขียนต่อเข้า InfluxDB
MQTT_BROKER = "127.0.0.1"
MQTT_TOPIC = f"traffic/{STUDENT_ID}"
MQTT_CLIENT_ID = f"traffic_pc_monitor_{STUDENT_ID}"

# broker กลางของอาจารย์ Kafka Connect ดึงจาก topic นี้เข้า traffic-events-6620301002
# รูปแบบ topic เป็นคอนเวนชันของวิชา iot/<รหัส>/traffic/<กล้อง>/<ชนิด>
CENTRAL_BROKER = "172.16.2.117"
CENTRAL_TOPIC = f"iot/{STUDENT_ID}/traffic/{CAMERA_ID}/events"


def connect_mqtt(host, client_id):
  client = mqtt.Client(client_id=client_id)
  try:
    client.connect(host, MQTT_PORT, keepalive=60)
    client.loop_start()
    print(f"เชื่อมต่อ MQTT สำเร็จ: {host}", file=sys.stderr)
  except Exception as e:
    print(f"เชื่อมต่อ MQTT ไม่สำเร็จ {host}: {e}", file=sys.stderr)
  return client


mqtt_client = connect_mqtt(MQTT_BROKER, MQTT_CLIENT_ID)
central_client = connect_mqtt(CENTRAL_BROKER, f"{MQTT_CLIENT_ID}_central")


def level_code(slow, n_vehicles):
  if n_vehicles >= MIN_VEHICLES:
    return next(i for i, (lim, _) in enumerate(LEVELS) if slow * 100 < lim)
  return 0  # ไม่มีรถ = ถนนไม่ติด ห้ามคืน None ปลายทางจะกลายเป็น null แล้วข้อมูลขาด


def pick_device():
  return (
      "cuda"
      if torch.cuda.is_available()
      else "mps"
      if torch.backends.mps.is_available()
      else "cpu"
  )


def load_roi_mask(path, width, height):
  img = cv2.imread(str(path))
  if img is None:
    raise FileNotFoundError(f"เปิดไฟล์ ROI ไม่ได้: {path}")
  b, g, r = cv2.split(img.astype(np.int16))
  red = ((r > 120) & (r - g > 60) & (r - b > 60)).astype(np.uint8) * 255
  red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
  if not red.any():
    raise ValueError(f"ไม่พบเส้นขอบสีแดงใน {path}")
  h, w = red.shape
  padded = cv2.copyMakeBorder(red, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
  cv2.floodFill(padded, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 255)
  filled = np.where(
      (padded[1:-1, 1:-1] == 0) | (red > 0), 255, 0
  ).astype(np.uint8)
  n, labels, stats, _ = cv2.connectedComponentsWithStats(filled, 8)
  if n > 1:
    filled = np.where(
        labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])), 255, 0
    ).astype(np.uint8)
  return (
      cv2.resize(filled, (width, height), interpolation=cv2.INTER_NEAREST)
      if filled.shape != (height, width)
      else filled
  )


class CongestionMonitor:

  def __init__(self, fps, sample_rate, hysteresis=10.0):
    self.fps, self.hysteresis, self.alert_active = fps, hysteresis, False
    self.window = collections.deque(
        maxlen=max(1, int(WINDOW_SEC * sample_rate))
    )
    self.last_seen, self.speed_ema = {}, {}

  def update_track(self, tid, frame_idx, cx, cy, box_h):
    prev = self.last_seen.get(tid)
    self.last_seen[tid] = (frame_idx, cx, cy)
    if prev is None:
      return None
    dt = (frame_idx - prev[0]) / self.fps
    if dt <= 0 or box_h <= 0:
      return None
    vlps = math.hypot(cx - prev[1], cy - prev[2]) / box_h / dt
    self.speed_ema[tid] = (
        vlps
        if tid not in self.speed_ema
        else SPEED_EMA * self.speed_ema[tid] + (1 - SPEED_EMA) * vlps
    )
    return self.speed_ema[tid]

  def commit_frame(self, n, speeds):
    self.window.append((n, speeds))

  def stale_ids(self, frame_idx, ttl):
    return [t for t, (f, _, _) in self.last_seen.items() if frame_idx - f > ttl]

  def forget(self, tid):
    self.last_seen.pop(tid, None)
    self.speed_ema.pop(tid, None)

  def stats(self):
    if not self.window:
      return {
          "level": "UNKNOWN",
          "alert": False,
          "veh": 0.0,
          "spd": 0.0,
          "slow": 0.0,
      }
    speeds = [v for _, sp in self.window for v in sp]
    mean_n = sum(n for n, _ in self.window) / len(self.window)
    pct = (
        sum(1 for v in speeds if v < SLOW_VLPS) / len(speeds) * 100
        if speeds
        else 0.0
    )
    enough = mean_n >= MIN_VEHICLES
    code = level_code(pct / 100, mean_n)
    level = "UNKNOWN" if code is None else LEVELS[code][1]
    warm = len(self.window) >= self.window.maxlen // 2
    if self.alert_active:
      self.alert_active = enough and pct >= JAM_PERCENT - self.hysteresis
    elif warm and enough and pct >= JAM_PERCENT:
      self.alert_active = True
    return {
        "level": level,
        "alert": self.alert_active,
        "veh": round(mean_n, 1),
        "spd": round(
            float(np.median(speeds)) if speeds else 0.0,
            2,
        ),
        "slow": round(pct / 100, 2),
    }


class IntervalStats:

  def __init__(self):
    self.reset()

  def reset(self):
    self.class_frames = collections.Counter()
    self.n_frames = 0
    self.speeds = []

  def commit_frame(self, roi_now, speeds):
    self.class_frames.update(roi_now)
    self.n_frames += 1
    self.speeds.extend(speeds)

  def snapshot(self):
    sp, n = self.speeds, max(self.n_frames, 1)
    return {
        "counts": {
            c: round(self.class_frames.get(c, 0) / n)
            for c in CLASS_NAMES.values()
        },
        "occ": round(sum(self.class_frames.values()) / n, 1),
        "slow": (
            round(sum(1 for v in sp if v < SLOW_VLPS) / len(sp), 2)
            if sp
            else 0.0
        ),
    }


def build_payload(s):
  c = s["counts"]
  return {
      "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
      "camera_id": CAMERA_ID,
      "student_id": STUDENT_ID,
      "car": c["car"],
      "motorcycle": c["motorcycle"],
      "bus": c["bus"],
      "truck": c["truck"],
      "vehicles_in_roi": sum(c.values()),
      "slow_vehicle_ratio": s["slow"],
      "congestion_level": level_code(s["slow"], s["occ"]),
  }


def emit(p):
  payload_str = json.dumps(p, ensure_ascii=False)
  print(json.dumps(p, indent=2, ensure_ascii=False), flush=True)
  # qos 1 ไป broker กลางเพราะเป็นข้อมูลที่ต้องส่งอาจารย์ ตกไม่ได้
  # ในเครื่องใช้ qos 0 พอ ตกก็รออีก 10 วิ
  for client, topic, qos in (
      (mqtt_client, MQTT_TOPIC, 0),
      (central_client, CENTRAL_TOPIC, 1),
  ):
    try:
      client.publish(topic, payload_str, qos=qos)
    except Exception as e:
      print(f"ส่ง MQTT ไม่สำเร็จ {topic}: {e}", file=sys.stderr)


def draw_hud(frame, cg, fps_live, roi_contours):
  if roi_contours is not None:
    cv2.drawContours(frame, roi_contours, -1, (0, 0, 255), 2)
  lines = [
      (
          "TRAFFIC: " + cg["level"],
          LEVEL_COLORS.get(cg["level"], LEVEL_COLORS["UNKNOWN"]),
      ),
      (
          "slow {:.0f}%  in-roi {:.1f}".format(cg["slow"] * 100, cg["veh"]),
          (255, 255, 255),
      ),
      ("speed {:.2f} veh-len/s".format(cg["spd"]), (255, 255, 255)),
      ("{:.1f} fps".format(fps_live), (200, 200, 200)),
  ]
  overlay = frame.copy()
  cv2.rectangle(overlay, (0, 0), (250, 18 * len(lines) + 14), (0, 0, 0), -1)
  cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
  for i, (text, col) in enumerate(lines):
    cv2.putText(
        frame,
        text,
        (8, 22 + i * 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        col,
        1,
        cv2.LINE_AA,
    )
  if cg["alert"]:
    cv2.rectangle(
        frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 4
    )


def main():
  ap = argparse.ArgumentParser(
      description="ตรวจจับความติดขัดจราจรจากวิดีโอ (พร้อมส่ง MQTT)"
  )
  ap.add_argument(
      "video",
      nargs="?",
      default="test.mov",
      help="ไฟล์วิดีโอ, RTSP URL, หรือเลขกล้อง (0 = webcam)",
  )
  ap.add_argument("--model", default="yolo26s.pt")
  ap.add_argument(
      "--roi", default="mapreal.png", help="ภาพขอบเขตเส้นแดง (none = ทั้งเฟรม)"
  )
  ap.add_argument("--no-show", action="store_true", help="ไม่เปิดหน้าต่างแสดงผล")
  ap.add_argument(
      "--loop",
      action="store_true",
      help="เล่นไฟล์วิดีโอวนซ้ำเมื่อจบคลิป (ใช้กับกล้องสดไม่ได้)",
  )
  args = ap.parse_args()

  for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
      s.reconfigure(encoding="utf-8", errors="replace")

  source = int(args.video) if args.video.isdigit() else args.video
  is_live = isinstance(source, int) or source.startswith(
      ("rtsp://", "http://", "https://")
  )
  cap = cv2.VideoCapture(source)
  if not cap.isOpened():
    sys.exit("เปิดวิดีโอไม่ได้: {}".format(args.video))
  width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
  height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
  fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
  interval_frames = max(1, int(fps * INTERVAL_SEC))

  roi_mask = roi_contours = None
  cx1, cy1, cx2, cy2 = 0, 0, width, height
  if args.roi and args.roi.lower() != "none":
    roi_mask = load_roi_mask(Path(args.roi), width, height)
    roi_contours, _ = cv2.findContours(
        roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    ys, xs = np.nonzero(roi_mask)
    cx1, cx2, cy1, cy2 = (
        int(xs.min()),
        int(xs.max()) + 1,
        int(ys.min()),
        int(ys.max()) + 1,
    )

  show, device = not args.no_show, pick_device()
  print(
      "video: {}x{} @ {:.1f}fps | device={}".format(width, height, fps, device),
      file=sys.stderr,
  )
  model = YOLO(args.model)
  monitor = CongestionMonitor(fps, fps / STRIDE)
  interval = IntervalStats()
  class_votes = collections.defaultdict(collections.Counter)
  track_ttl = int(fps * TRACK_TTL_SEC)
  was_alerting = paused = False
  loops = 0
  frame_idx, freq = 0, cv2.getTickFrequency()
  start_tick = last_emit = cv2.getTickCount()

  while True:
    if paused:
      pause_tick = cv2.getTickCount()
      key = cv2.waitKey(30) & 0xFF
      if key in (ord("q"), 27):
        break
      paused = key != ord(" ")
      start_tick += cv2.getTickCount() - pause_tick
      continue

    tick = cv2.getTickCount()
    for _ in range(STRIDE - 1):
      if cap.grab():
        frame_idx += 1
    ret, frame = cap.read()
    if not ret:
      if not args.loop or is_live:
        break
      cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
      ret, frame = cap.read()
      if not ret:
        print("ย้อนกลับต้นคลิปไม่สำเร็จ หยุดทำงาน", file=sys.stderr)
        break
      # ล้าง track เดิมทิ้ง ไม่งั้นภาพที่กระโดดกลับต้นคลิปจะถูกคิดเป็น
      # รถวิ่งข้ามจอในเฟรมเดียว แล้วความเร็วจะพุ่งผิด
      monitor.last_seen.clear()
      monitor.speed_ema.clear()
      class_votes.clear()
      loops += 1
      print(f"วนคลิปรอบที่ {loops}", file=sys.stderr)
    frame_idx += 1

    results = model.track(
        frame[cy1:cy2, cx1:cx2],
        persist=True,
        tracker=TRACKER,
        imgsz=IMGSZ,
        classes=list(CLASS_NAMES),
        conf=min(CONF_THR.values()),
        verbose=False,
        device=device,
    )
    boxes = results[0].boxes
    frame_speeds = []
    roi_now = collections.Counter()
    if boxes is not None and boxes.id is not None:
      for box, tid, cls_id, conf in zip(
          boxes.xyxy.cpu().numpy(),
          boxes.id.int().cpu().numpy(),
          boxes.cls.int().cpu().numpy(),
          boxes.conf.cpu().numpy(),
      ):
        x1, y1 = int(box[0]) + cx1, int(box[1]) + cy1
        x2, y2 = int(box[2]) + cx1, int(box[3]) + cy1
        vtype = CLASS_NAMES.get(int(cls_id))
        if (
            vtype is None
            or conf < CONF_THR[int(cls_id)]
            or (x2 - x1) * (y2 - y1) > width * height * MAX_BOX_AREA_RATIO
        ):
          continue
        ax = min(max((x1 + x2) // 2, 0), width - 1)
        ay = min(max(y2, 0), height - 1)
        if roi_mask is not None and roi_mask[ay, ax] == 0:
          continue
        tid = int(tid)
        class_votes[tid][vtype] += 1
        roi_now[class_votes[tid].most_common(1)[0][0]] += 1
        speed = monitor.update_track(
            tid, frame_idx, (x1 + x2) / 2, (y1 + y2) / 2, y2 - y1
        )
        if speed is not None:
          frame_speeds.append(speed)
        if show:
          label = "{}#{}".format(vtype, tid) + (
              "" if speed is None else " {:.1f}".format(speed)
          )
          cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
          cv2.putText(
              frame,
              label,
              (x1, max(y1 - 6, 12)),
              cv2.FONT_HERSHEY_SIMPLEX,
              0.45,
              (0, 255, 0),
              1,
              cv2.LINE_AA,
          )

    monitor.commit_frame(sum(roi_now.values()), frame_speeds)
    interval.commit_frame(roi_now, frame_speeds)
    congestion = monitor.stats()
    for stale in monitor.stale_ids(frame_idx, track_ttl):
      class_votes.pop(stale, None)
      monitor.forget(stale)
    fps_live = freq / max(cv2.getTickCount() - tick, 1)

    if congestion["alert"] != was_alerting:
      was_alerting = congestion["alert"]
      print(
          "[{}] t={:.1f}s รถช้า {:.0f}% ใน ROI {:.1f} คัน".format(
              "JAM" if was_alerting else "CLEARED",
              frame_idx / fps,
              congestion["slow"] * 100,
              congestion["veh"],
          ),
          file=sys.stderr,
      )

    due = (
        (cv2.getTickCount() - last_emit) / freq >= INTERVAL_SEC
        if is_live
        else frame_idx % interval_frames < STRIDE
    )
    if due:
      last_emit = cv2.getTickCount()
      emit(build_payload(interval.snapshot()))
      interval.reset()

    if show:
      draw_hud(frame, congestion, fps_live, roi_contours)
      cv2.imshow("Traffic Monitor", frame)
      wait_ms = 1
      if REALTIME:
        behind = frame_idx / fps - (cv2.getTickCount() - start_tick) / freq
        if behind < -1.0:
          start_tick = cv2.getTickCount() - int(frame_idx / fps * freq)
        else:
          wait_ms = max(1, int(behind * 1000))
      key = cv2.waitKey(wait_ms) & 0xFF
      if key in (ord("q"), 27):
        break
      paused = key == ord(" ")

  print("=== FINAL ===", file=sys.stderr)
  emit(build_payload(interval.snapshot()))

  # ปิดการเชื่อมต่อ MQTT และทำความสะอาดหน้าต่าง
  for client in (mqtt_client, central_client):
    client.loop_stop()
    client.disconnect()
  cap.release()
  cv2.destroyAllWindows()


if __name__ == "__main__":
  main()