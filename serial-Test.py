import serial
import time
import threading
import cv2
from picamera2 import Picamera2
from ultralytics import YOLO
from pyzbar.pyzbar import decode


# -------------------------------
# Serial Initialization
# -------------------------------
arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(2)
arduino.reset_input_buffer()

# -------------------------------
# Shared State
# -------------------------------
latest_frame = None
annotated_display = None
stop_flag = False
object_info = {"label": None, "confidence": 0.0}
qr_found = None
distances = {"FRONT": None, "LEFT": None, "RIGHT": None}
current_cmd = None
frame_lock = threading.Lock()
serial_lock = threading.Lock()

# -------------------------------
# YOLO / Camera
# -------------------------------
model = YOLO("yolov8n.pt")
cam = Picamera2()
config = cam.create_preview_configuration(
    main={"format": "RGB888", "size": (320, 240)}
)
cam.configure(config)
cam.start()

# -------------------------------
# Helper functions
# -------------------------------
def send_command(cmd):
    global current_cmd
    with serial_lock:
        arduino.write(cmd.encode())
    current_cmd = cmd
    print(f"[SEND CMD] {cmd}")

def send_message(msg):
    with serial_lock:
        arduino.write((msg + "\n").encode())
    print(f"[SEND MSG] {msg}")

# -------------------------------
# Capture Thread
# -------------------------------
def capture_frames():
    global latest_frame
    while not stop_flag:
        frame = cam.capture_array()
        with frame_lock:
            latest_frame = frame

# -------------------------------
# Detection Thread
# -------------------------------
def run_detection():
    global object_info, qr_found, annotated_display
    while not stop_flag:
        with frame_lock:
            if latest_frame is None:
                continue
            frame = latest_frame.copy()

        # ---------------- YOLO ----------------
        results = model(frame)
        annotated = results[0].plot()

        # Top object info
        if len(results[0].boxes) > 0:
            cls_id = int(results[0].boxes.cls[0])
            conf = float(results[0].boxes.conf[0])
            label = model.names[cls_id]
            object_info = {"label": label, "confidence": conf}
        else:
            object_info = {"label": None, "confidence": 0.0}

        # ---------------- QR ----------------
        qrs = decode(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY))
        qr_found = None
        for qr in qrs:
            x, y, w, h = qr.rect
            cv2.rectangle(annotated, (x, y), (x+w, y+h), (0,0,255), 3)
            text = qr.data.decode("utf-8")
            qr_found = text
            cv2.putText(annotated, text, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            print(f"[QR] {text}")

        # ---------------- Overlay Info ----------------
        info_text = f"Obj: {object_info['label']} ({object_info['confidence']:.2f})" if object_info["label"] else "Obj: None"
        dist_text = f"Dists F:{distances['FRONT']} L:{distances['LEFT']} R:{distances['RIGHT']}"
        cmd_text  = f"Cmd: {current_cmd}"
        y_text = 20
        for txt in [info_text, dist_text, cmd_text]:
            cv2.putText(annotated, txt, (10, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 2)
            y_text += 20

        annotated_display = annotated
        time.sleep(0.05)

# -------------------------------
# Serial Listener
# -------------------------------
def serial_listener():
    global distances
    while not stop_flag:
        if arduino.in_waiting:
            with serial_lock:
                line = arduino.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith("D:"):
                handle_distance_message(line)
        time.sleep(0.05)

def handle_distance_message(msg):
    global distances
    print("[Arduino]", msg)
    try:
        parts = msg.replace("D:", "").split(";")
        data = {p.split("=")[0]: int(p.split("=")[1]) for p in parts}
        distances.update(data)
    except Exception as e:
        print("Parse error:", e)
        return

    # --- Decision Logic ---
    if qr_found:
        print("QR detected — stop.")
        send_command('S')
        return

    label = object_info["label"]
    conf = object_info["confidence"]
    if label:
        send_message(f"O:{label}")
        print(f"[DETECTION] {label} ({conf:.2f})")

    L, R = distances["LEFT"], distances["RIGHT"]
    if (L is not None and R is not None):
        if L > R:
            send_command('L')
        elif R > L:
            send_command('R')
        else:
            send_command('B')

# -------------------------------
# Start Threads
# -------------------------------
threads = [
    threading.Thread(target=capture_frames),
    threading.Thread(target=run_detection),
    threading.Thread(target=serial_listener)
]
for t in threads:
    t.start()

print("Running Unified Vision + Ultrasonic + GUI — press 'q' to quit.")

# -------------------------------
# GUI Display Loop
# -------------------------------
while True:
    if annotated_display is not None:
        cv2.imshow("Raspberry Pi Vision", annotated_display)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        stop_flag = True
        break

# -------------------------------
# Cleanup
# -------------------------------
for t in threads: t.join()
cam.stop()
arduino.close()
cv2.destroyAllWindows()
print("Stopped successfully.")