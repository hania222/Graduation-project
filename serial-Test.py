"""
robot_controller.py
- Runs on Raspberry Pi
- Uses camera for YOLO object detection and QR code scanning
- Publishes status and events to MQTT broker
- Subscribes to task assignments from backend
- Controls Arduino robot via Serial

Requirements:
pip install opencv-python pyzbar ultralytics paho-mqtt picamera2 pyserial

Run:
python robot_controller.py
"""

import time
import threading
import cv2
from picamera2 import Picamera2
from ultralytics import YOLO
from pyzbar.pyzbar import decode
import paho.mqtt.client as mqtt
import json
import random
from datetime import datetime
import serial
import serial.tools.list_ports

# Configuration
# ===============================
ROBOT_ID = 1
ROBOT_NAME = "Robot-01"
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883

# Serial Configuration for Arduino
ARDUINO_PORT = "/dev/ttyACM0"  # ← Changed from ttyUSB0 to ttyACM0
ARDUINO_BAUD = 9600
ARDUINO_TIMEOUT = 2

# MQTT Topics
TOPIC_STATUS = "warehouse/robot/status"
TOPIC_LOGS = "warehouse/robot/logs"
TOPIC_TASKS = "warehouse/tasks"

# Task Action to Movement Mapping
ACTION_MOVEMENT_MAP = {
    "Pick": "R",      # Pick -> Turn Right
    "Place": "L",     # Place -> Turn Left
    "Scan": "F",      # Scan -> Forward
    "Move": "B"       # Move -> Backward
}

# ===============================
# Global State
# ===============================
latest_frame = None
annotated_display = None
stop_flag = False
frame_lock = threading.Lock()

current_task = None
task_lock = threading.Lock()
qr_processed = set()

robot_state = {
    "status": "idle",
    "battery": 100,
    "x_pos": 0,
    "y_pos": 0,
    "current_task_id": None
}

# Arduino serial connection
arduino_serial = None
arduino_lock = threading.Lock()

# ===============================
# Arduino Serial Functions
# ===============================
def find_arduino_port():
    """Auto-detect Arduino port"""
    ports = serial.tools.list_ports.comports()
    
    for port in ports:
        # Common Arduino identifiers
        if "USB" in port.device or "ACM" in port.device:
            print(f"[ARDUINO] Found potential port: {port.device} - {port.description}")
            return port.device
        if "Arduino" in port.description or "CH340" in port.description:
            print(f"[ARDUINO] Found Arduino: {port.device}")
            return port.device
    
    return None


def connect_arduino():
    """Connect to Arduino via serial"""
    global arduino_serial
    
    # Try configured port first, then auto-detect
    port = ARDUINO_PORT
    
    if not port:
        port = find_arduino_port()
    
    if not port:
        print("[ARDUINO] No Arduino port found!")
        print("[ARDUINO] Available ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  - {p.device}: {p.description}")
        return False
    
    try:
        arduino_serial = serial.Serial(
            port=port,
            baudrate=ARDUINO_BAUD,
            timeout=ARDUINO_TIMEOUT
        )
        
        # Wait for Arduino to reset
        time.sleep(2)
        
        # Clear any startup messages
        arduino_serial.reset_input_buffer()
        
        # Test connection
        arduino_serial.write(b'P')  # Ping
        time.sleep(0.5)
        
        response = ""
        while arduino_serial.in_waiting:
            response += arduino_serial.readline().decode('utf-8').strip()
        
        if "PONG" in response or "READY" in response:
            print(f"[ARDUINO] Connected successfully on {port}")
            return True
        else:
            print(f"[ARDUINO] Connected but no valid response: {response}")
            return True  # Still connected, might work
            
    except serial.SerialException as e:
        print(f"[ARDUINO] Connection error: {e}")
        return False
    except Exception as e:
        print(f"[ARDUINO] Unexpected error: {e}")
        return False


def send_arduino_command(command):
    """Send command to Arduino and wait for acknowledgment"""
    global arduino_serial
    
    if arduino_serial is None or not arduino_serial.is_open:
        print("[ARDUINO] Not connected!")
        return False, "Not connected"
    
    with arduino_lock:
        try:
            # Clear input buffer
            arduino_serial.reset_input_buffer()
            
            # Send command
            arduino_serial.write(command.encode())
            print(f"[ARDUINO] Sent: {command}")
            
            # Wait for acknowledgment
            time.sleep(0.1)
            
            responses = []
            timeout_start = time.time()
            
            while time.time() - timeout_start < 3:  # 3 second timeout
                if arduino_serial.in_waiting:
                    line = arduino_serial.readline().decode('utf-8').strip()
                    if line:
                        responses.append(line)
                        print(f"[ARDUINO] Received: {line}")
                        
                        if line.startswith("DONE:"):
                            return True, responses
                
                time.sleep(0.1)
            
            if responses:
                return True, responses
            else:
                return False, "No response"
                
        except serial.SerialException as e:
            print(f"[ARDUINO] Serial error: {e}")
            return False, str(e)
        except Exception as e:
            print(f"[ARDUINO] Error: {e}")
            return False, str(e)


def execute_movement(action):
    """Execute movement based on task action"""
    command = ACTION_MOVEMENT_MAP.get(action, "S")  # Default to Stop
    
    action_descriptions = {
        "R": "turning RIGHT",
        "L": "turning LEFT", 
        "F": "moving FORWARD",
        "B": "moving BACKWARD",
        "S": "stopping"
    }
    
    description = action_descriptions.get(command, "unknown movement")
    print(f"[MOVEMENT] Action '{action}' -> {description}")
    
    success, response = send_arduino_command(command)
    
    if success:
        publish_log(f"Movement executed: {action} -> {description}")
    else:
        publish_log(f"Movement failed: {action} -> {response}")
    
    return success


# ===============================
# Camera & YOLO Setup
# ===============================
print("[INIT] Loading YOLO model...")
model = YOLO("yolov8n.pt")
print("[INIT] YOLO model loaded")

print("[INIT] Starting camera...")
cam = Picamera2()
config = cam.create_preview_configuration(
    main={"format": "RGB888", "size": (640, 480)}
)
cam.configure(config)
cam.start()
print("[INIT] Camera started")

# ===============================
# MQTT Setup
# ===============================
mqtt_client = mqtt.Client()


def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    if rc == 0:
        print("[MQTT] Connected to broker successfully")
        client.subscribe(TOPIC_TASKS)
        print(f"[MQTT] Subscribed to {TOPIC_TASKS}")
    else:
        print(f"[MQTT] Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """Callback when message received"""
    global current_task
    
    try:
        if msg.topic == TOPIC_TASKS:
            data = json.loads(msg.payload.decode())
            print(f"[MQTT] Received task: {data}")
            
            task_id = data.get("task_id")
            action = data.get("action", "Pick")
            container_id = data.get("container_id")
            
            with task_lock:
                current_task = data
                robot_state["current_task_id"] = task_id
                robot_state["status"] = "busy"
            
            # Log task receipt
            publish_log(f"Received task {task_id}: {action} container {container_id}")
            publish_status()
            
            # Execute the movement based on action
            print(f"[TASK] Executing action: {action}")
            success = execute_movement(action)
            
            if success:
                # Update position based on action (simulated)
                update_position_for_action(action)
                
                # Small delay to simulate task execution
                time.sleep(0.5)
                
                # Mark task as completed
                publish_log(f"Task {task_id} completed: {action}")
                publish_task_completed(task_id)
            else:
                publish_log(f"Task {task_id} failed: movement error")
                robot_state["status"] = "error"
                publish_status()
            
            with task_lock:
                current_task = None
                
    except json.JSONDecodeError as e:
        print(f"[MQTT] JSON decode error: {e}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")


def update_position_for_action(action):
    """Update simulated position based on action"""
    if action == "Pick":  # Right
        robot_state["x_pos"] = min(10, robot_state["x_pos"] + 1)
    elif action == "Place":  # Left
        robot_state["x_pos"] = max(0, robot_state["x_pos"] - 1)
    elif action == "Scan":  # Forward
        robot_state["y_pos"] = min(10, robot_state["y_pos"] + 1)
    elif action == "Move":  # Backward
        robot_state["y_pos"] = max(0, robot_state["y_pos"] - 1)


def on_disconnect(client, userdata, rc):
    """Callback when disconnected"""
    print(f"[MQTT] Disconnected with code {rc}")


mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.on_disconnect = on_disconnect


def connect_mqtt():
    """Connect to MQTT broker with retry"""
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            mqtt_client.loop_start()
            print("[MQTT] Client loop started")
            return True
        except Exception as e:
            retry_count += 1
            print(f"[MQTT] Connection attempt {retry_count} failed: {e}")
            time.sleep(2)
    
    print("[MQTT] Failed to connect after maximum retries")
    return False


# ===============================
# Publishing Functions
# ===============================
def publish_status():
    """Publish robot status to MQTT"""
    msg = {
        "robot_id": ROBOT_ID,
        "name": ROBOT_NAME,
        "status": robot_state["status"],
        "battery": robot_state["battery"],
        "x_pos": robot_state["x_pos"],
        "y_pos": robot_state["y_pos"],
        "task_id": robot_state["current_task_id"],
        "timestamp": datetime.now().timestamp()
    }
    
    try:
        mqtt_client.publish(TOPIC_STATUS, json.dumps(msg))
        print(f"[STATUS] Published: {robot_state['status']}, Battery: {robot_state['battery']}%")
    except Exception as e:
        print(f"[STATUS] Failed to publish: {e}")


def publish_log(message):
    """Publish log message to MQTT"""
    msg = {
        "robot_id": ROBOT_ID,
        "task_id": robot_state["current_task_id"],
        "message": message,
        "timestamp": datetime.now().timestamp()
    }
    
    try:
        mqtt_client.publish(TOPIC_LOGS, json.dumps(msg))
        print(f"[LOG] {message}")
    except Exception as e:
        print(f"[LOG] Failed to publish: {e}")


def publish_qr_event(qr_data):
    """Publish QR code detection event"""
    msg = {
        "robot_id": ROBOT_ID,
        "event": "QR_CONFIRMED",
        "qr_data": qr_data,
        "status": "busy",
        "battery": robot_state["battery"],
        "x_pos": robot_state["x_pos"],
        "y_pos": robot_state["y_pos"],
        "task_id": robot_state["current_task_id"],
        "timestamp": datetime.now().timestamp()
    }
    
    try:
        mqtt_client.publish(TOPIC_STATUS, json.dumps(msg))
        print(f"[QR] Event published: {qr_data}")
    except Exception as e:
        print(f"[QR] Failed to publish event: {e}")


def publish_task_completed(task_id):
    """Publish task completion status"""
    robot_state["status"] = "completed"
    robot_state["current_task_id"] = task_id
    
    msg = {
        "robot_id": ROBOT_ID,
        "status": "completed",
        "battery": robot_state["battery"],
        "x_pos": robot_state["x_pos"],
        "y_pos": robot_state["y_pos"],
        "task_id": task_id,
        "timestamp": datetime.now().timestamp()
    }
    
    try:
        mqtt_client.publish(TOPIC_STATUS, json.dumps(msg))
        print(f"[TASK] Task {task_id} completed")
    except Exception as e:
        print(f"[TASK] Failed to publish completion: {e}")
    
    # Reset state
    time.sleep(0.5)
    robot_state["status"] = "idle"
    robot_state["current_task_id"] = None
    publish_status()


# ===============================
# Worker Threads
# ===============================
def capture_frames():
    """Thread: Continuously capture frames from camera"""
    global latest_frame
    
    print("[CAPTURE] Thread started")
    
    while not stop_flag:
        try:
            frame = cam.capture_array()
            with frame_lock:
                latest_frame = frame
            time.sleep(0.03)
        except Exception as e:
            print(f"[CAPTURE] Error: {e}")
            time.sleep(0.1)
    
    print("[CAPTURE] Thread stopped")


def run_detection():
    """Thread: Run YOLO and QR detection on captured frames"""
    global annotated_display
    
    print("[DETECTION] Thread started")
    
    while not stop_flag:
        with frame_lock:
            if latest_frame is None:
                time.sleep(0.05)
                continue
            frame = latest_frame.copy()
        
        try:
            # YOLO Object Detection
            results = model(frame, verbose=False)
            annotated = results[0].plot()
            
            # QR Code Detection
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            qr_codes = decode(gray)
            
            for qr in qr_codes:
                x, y, w, h = qr.rect
                cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 0, 255), 3)
                
                qr_data = qr.data.decode('utf-8')
                cv2.putText(annotated, qr_data, (x, y - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                if qr_data not in qr_processed:
                    qr_processed.add(qr_data)
                    print(f"[QR] Detected: {qr_data}")
                    publish_qr_event(qr_data)
                    publish_log(f"QR Code scanned: {qr_data}")
            
            # Add status overlay
            status_text = f"Status: {robot_state['status']} | Battery: {robot_state['battery']}%"
            cv2.putText(annotated, status_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            pos_text = f"Position: ({robot_state['x_pos']}, {robot_state['y_pos']})"
            cv2.putText(annotated, pos_text, (10, 55),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            if robot_state["current_task_id"]:
                task_text = f"Task: {robot_state['current_task_id']}"
                cv2.putText(annotated, task_text, (10, 80),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            
            # Arduino connection status
            arduino_status = "Arduino: Connected" if (arduino_serial and arduino_serial.is_open) else "Arduino: Disconnected"
            color = (0, 255, 0) if (arduino_serial and arduino_serial.is_open) else (0, 0, 255)
            cv2.putText(annotated, arduino_status, (10, 105),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            annotated_display = annotated
            
        except Exception as e:
            print(f"[DETECTION] Error: {e}")
        
        time.sleep(0.05)
    
    print("[DETECTION] Thread stopped")


def status_publisher():
    """Thread: Periodically publish robot status"""
    print("[STATUS] Thread started")
    
    while not stop_flag:
        if robot_state["battery"] > 10:
            robot_state["battery"] -= random.randint(0, 1)
        
        publish_status()
        time.sleep(5)
    
    print("[STATUS] Thread stopped")


def battery_simulator():
    """Thread: Simulate battery charging when idle"""
    print("[BATTERY] Thread started")
    
    while not stop_flag:
        if robot_state["status"] == "idle" and robot_state["battery"] < 100:
            robot_state["battery"] = min(100, robot_state["battery"] + 1)
        time.sleep(10)
    
    print("[BATTERY] Thread stopped")


# ===============================
# Manual Control (for testing)
# ===============================
def manual_control_handler(key):
    """Handle manual control keys for testing"""
    if key == ord('w'):
        print("[MANUAL] Forward")
        send_arduino_command('F')
    elif key == ord('s'):
        print("[MANUAL] Backward")
        send_arduino_command('B')
    elif key == ord('a'):
        print("[MANUAL] Left")
        send_arduino_command('L')
    elif key == ord('d'):
        print("[MANUAL] Right")
        send_arduino_command('R')
    elif key == ord('x'):
        print("[MANUAL] Stop")
        send_arduino_command('S')


# ===============================
# Main Execution
# ===============================
def main():
    global stop_flag
    
    print("=" * 50)
    print(f"🤖 {ROBOT_NAME} (ID: {ROBOT_ID}) Starting...")
    print("=" * 50)
    
    # Connect to Arduino
    print("\n[INIT] Connecting to Arduino...")
    arduino_connected = connect_arduino()
    if arduino_connected:
        print("[INIT] Arduino connected!")
    else:
        print("[INIT] Arduino not connected - movement commands will fail")
        print("[INIT] Continuing anyway for testing...")
    
    # Connect to MQTT
    print("\n[INIT] Connecting to MQTT...")
    if not connect_mqtt():
        print("[ERROR] Cannot start without MQTT connection")
        return
    
    # Start worker threads
    threads = [
        threading.Thread(target=capture_frames, name="CaptureThread"),
        threading.Thread(target=run_detection, name="DetectionThread"),
        threading.Thread(target=status_publisher, name="StatusThread"),
        threading.Thread(target=battery_simulator, name="BatteryThread")
    ]
    
    for t in threads:
        t.daemon = True
        t.start()
    
    # Initial status
    publish_log(f"{ROBOT_NAME} started and ready")
    publish_status()
    
    print("=" * 50)
    print("🤖 Robot running!")
    print("=" * 50)
    print("\nControls:")
    print("  Q - Quit")
    print("  R - Reset QR history")
    print("  W/A/S/D - Manual movement (Forward/Left/Backward/Right)")
    print("  X - Stop motors")
    print("=" * 50)
    
    # Display loop
    try:
        while True:
            if annotated_display is not None:
                display_frame = cv2.cvtColor(annotated_display, cv2.COLOR_RGB2BGR)
                cv2.imshow(f"Robot Vision - {ROBOT_NAME}", display_frame)
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                print("\n[MAIN] Quit command received")
                break
            elif key == ord('r'):
                qr_processed.clear()
                print("[MAIN] QR code history cleared")
            elif key in [ord('w'), ord('a'), ord('s'), ord('d'), ord('x')]:
                manual_control_handler(key)
                
    except KeyboardInterrupt:
        print("\n[MAIN] Keyboard interrupt received")
    
    # Cleanup
    print("[MAIN] Shutting down...")
    stop_flag = True
    
    # Stop motors
    if arduino_serial and arduino_serial.is_open:
        send_arduino_command('S')
        arduino_serial.close()
        print("[ARDUINO] Connection closed")
    
    # Wait for threads
    for t in threads:
        t.join(timeout=2)
    
    # Stop camera
    cam.stop()
    cv2.destroyAllWindows()
    
    # Disconnect MQTT
    publish_log(f"{ROBOT_NAME} shutting down")
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    
    print("=" * 50)
    print("🛑 Robot stopped cleanly")
    print("=" * 50)


if __name__ == "__main__":
    main()