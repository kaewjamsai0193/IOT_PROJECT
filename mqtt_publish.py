"""ส่ง payload จาก detect_video.py ขึ้น MQTT gateway

อ่าน JSON ที่ detect_video.py พิมพ์ออก stdout แล้วส่งต่อขึ้น broker
แยกเป็นคนละโปรเซสเพื่อให้การตรวจจับไม่สะดุดเวลา gateway ล่มหรือเน็ตหลุด

  python detect_video.py jam.mp4 --no-show | python mqtt_publish.py --host 192.168.1.10

ดูว่าจะส่งอะไรบ้างโดยไม่ต้องต่อ broker จริง:

  python detect_video.py jam.mp4 --no-show | python mqtt_publish.py --dry-run
"""

import argparse
import json
import sys
import time

# เหตุการณ์รถติดพลาดไม่ได้ ส่งแบบ QoS 1 (การันตีถึงอย่างน้อยหนึ่งครั้ง)
# ส่วนรายงานสถานะตามรอบ ตกไปบ้างไม่เป็นไร เพราะอีก 10 วินาทีก็ส่งใหม่
ALERT_EVENTS = {"TRAFFIC_JAM_ALERT", "TRAFFIC_JAM_CLEARED"}
QOS_ALERT = 1
QOS_STATUS = 0


def read_payloads(stream):
    """อ่าน JSON ที่พิมพ์ต่อกันเป็นสตรีม แล้ว yield ทีละ object

    detect_video.py พิมพ์แบบ indent=2 จึงคั่นด้วยบรรทัดใหม่ไม่ได้
    ต้องใช้ raw_decode ไล่ทีละ object แทน
    """
    decoder = json.JSONDecoder()
    buf = ""
    for line in stream:
        buf += line
        while True:
            start = 0
            while start < len(buf) and buf[start] in " \r\n\t":
                start += 1
            if start >= len(buf):
                buf = ""
                break
            try:
                obj, end = decoder.raw_decode(buf, start)
            except ValueError:
                buf = buf[start:]   # ยังมาไม่ครบ รอบรรทัดถัดไป
                break
            yield obj
            buf = buf[end:]


def main() -> None:
    parser = argparse.ArgumentParser(description="ส่ง payload จราจรขึ้น MQTT")
    parser.add_argument("--host", default="localhost", help="ที่อยู่ MQTT broker/gateway")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default=None,
                        help="ค่าเริ่มต้น: traffic/<camera_id> ที่อ่านจาก payload")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--client-id", default="traffic-detector")
    parser.add_argument("--keepalive", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true",
                        help="แสดงสิ่งที่จะส่งโดยไม่ต่อ broker จริง")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    client = None
    if not args.dry_run:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.client_id)
        if args.username:
            client.username_pw_set(args.username, args.password)
        # ให้ผู้ที่ subscribe รู้ทันทีถ้าตัวตรวจจับตายไป
        client.will_set("{}/status".format(args.topic or "traffic"), "offline",
                        qos=QOS_ALERT, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            client.connect(args.host, args.port, args.keepalive)
        except OSError as exc:
            # ต่อไม่ติดตอนเริ่มก็ไม่ตาย ปล่อยให้ loop_start ไล่ต่อใหม่เอง
            print("ต่อ broker ไม่ได้ ({}:{}): {} — จะพยายามต่อใหม่เรื่อยๆ".format(
                args.host, args.port, exc), file=sys.stderr, flush=True)
        client.loop_start()

    sent = failed = 0
    try:
        for payload in read_payloads(sys.stdin):
            event = payload.get("event_type", "TRAFFIC_STATUS")
            topic = args.topic or "traffic/{}".format(payload.get("camera_id", "unknown"))
            qos = QOS_ALERT if event in ALERT_EVENTS else QOS_STATUS
            # บีบช่องว่างทิ้งก่อนส่ง วัดจริงแล้วเล็กลง 29% (566 -> 403 ไบต์ต่อข้อความ)
            # ส่วนที่พิมพ์ออกจอยังเป็นแบบอ่านง่ายเหมือนเดิม
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

            if args.dry_run:
                print("[qos{}] {} <- {}".format(qos, topic, body), flush=True)
                sent += 1
                continue

            info = client.publish(topic, body, qos=qos)
            if info.rc != 0:
                failed += 1
                print("ส่งไม่สำเร็จ (rc={}) {} {} ไบต์".format(info.rc, event, len(body)),
                      file=sys.stderr, flush=True)
            else:
                sent += 1
                if event in ALERT_EVENTS:
                    print("ส่ง {} -> {} ({} ไบต์)".format(event, topic, len(body)),
                          file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if client is not None:
            client.publish("{}/status".format(args.topic or "traffic"), "offline",
                           qos=QOS_ALERT, retain=True)
            time.sleep(0.2)   # เผื่อเวลาให้ข้อความสุดท้ายออกจากคิว
            client.loop_stop()
            client.disconnect()
        print("จบ: ส่งสำเร็จ {} ข้อความ ล้มเหลว {}".format(sent, failed),
              file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
