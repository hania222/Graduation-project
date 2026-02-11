"""
- Runs on Raspberry Pi
- Line following + wide black patch detection
- QR confirmation
- FSM-driven logic
- Publishes robot status & events to backend
- Controls Arduino via Serial
"""

import time                         #for delays
import json                         #converts python objects
import threading
import serial                       #lets Pi commuincate with arduino via USB
import paho.mqtt.client as mqtt     #MQTT client library
from enum import Enum               #ensures states are fixed and safe
from datetime import datetime
from pyzbar.pyzbar import decode  
from picamera2 import Picamera2
import cv2
import numpy as np


# Configuration
ROBOT_ID = 1
ROBOT_NAME = "Robot-01"
BROKER_HOST = "127.0.0.1"      #MQTT broker IP (localhost)
BROKER_PORT = 1883             #default MQTT port, like HTTP uses 80
QR_SCAN_TIMEOUT = 10           #seconds to try scanning QR before failing
ARDUINO_PORT = "/dev/ttyACM0"  #linux device name for ardunio USB
ARDUINO_BAUD = 9600
lock = threading.Lock()

#Visual feed settings
SHOW_CAMERA_FEED = True #set to True to see the camera feed with detected QR codes (for debugging)
WINDOW_NAME="ROBOT CAMERA-QR Scanner"

TOPIC_TASK_ASSIGN = "warehouse/tasks/assign"
TOPIC_ROBOT_STATUS = "warehouse/robot/status"
TOPIC_ROBOT_EVENTS = "warehouse/robot/events"


# FSM States
class FSMState(Enum):
    IDLE = "IDLE"
    FOLLOW_LINE = "FOLLOW_LINE"
    AT_TARGET = "AT_TARGET"
    SCAN_QR = "SCAN_QR"
    ALIGN = "ALIGN"
    PICK_SIM = "PICK_SIM"
    DELIVER = "DELIVER"
    DROP_SIM = "DROP_SIM"
    ERROR = "ERROR"

# Global State
fsm_state = FSMState.IDLE  #current robot state(starts idle)
current_task = None
stop_flag = False
arduino=None
#arduino feedback flags
wide_black_detected = False
align_done = False

robot_state = {
    "status": "idle",
    "fsm_state": fsm_state.value,
    "battery": 100,
    "task_id": None
}


# Arduino Communication
def connect_arduino():
    global arduino 
    try:
        arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1) #arduino -> is the serial object connected to ardunio 
        time.sleep(2)
        print("[ARDUINO] Connected")
        return True
    except Exception as e:
        print("[ARDUINO] Connection failed:", e)
        return False

#sends simple commands to arduino, like "LF" for line follow or "S" for stop
def send_cmd(cmd):
    if arduino and arduino.is_open:
        arduino.write((cmd + "\n").encode())
        print(f"[ARDUINO] -> {cmd}")

#read commands from arduino, like "WIDE_BLACK" when it detects the wide black patch or "ALIGN_OK" when alignment is done
def read_arduino_line():
    if arduino and arduino.in_waiting: #in_waiting means there is data from arduino waiting to be read
        return arduino.readline().decode().strip()  #decode: converts bytes to strings
    return None

def arduino_listener():
    global wide_black_detected, align_done
    while not stop_flag:
        line=read_arduino_line()
        if not line:
            time.sleep(0.05)
            continue
        print(f"[ARDUINO] <- {line}")

        if line=="WIDE_BLACK":
            wide_black_detected = True
            publish_event("ARDUINO_WIDE_BLACK")

        elif line=="ALIGN_OK":
            align_done = True
            publish_event("ARDUINO_ALIGN_OK")

        elif line=="ALIGN_TIMEOUT":
            publish_event("ARDUINO_ALIGN_TIMEOUT")
            
# MQTT Setup
mqtt_client = mqtt.Client()

def publish_status():
    msg = {
        "robot_id": ROBOT_ID,
        "status": robot_state["status"],
        "fsm_state": fsm_state.value,
        "battery": robot_state["battery"]
    }
    mqtt_client.publish(TOPIC_ROBOT_STATUS, json.dumps(msg))

def publish_event(event, details=""): #default is an empty string
    msg = {
        "robot_id": ROBOT_ID,
        "task_id": robot_state["task_id"],
        "event": event,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
    mqtt_client.publish(TOPIC_ROBOT_EVENTS, json.dumps(msg))

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected")
        client.subscribe(TOPIC_TASK_ASSIGN)
    else:
        print("[MQTT] Connection failed")


def on_message(client, userdata, msg):
    global current_task, fsm_state
    data = json.loads(msg.payload.decode())
    if fsm_state != FSMState.IDLE:
        return  #ignore new tasks if busy
    current_task=data
    robot_state["task_id"]=data['task_id']
    robot_state["status"]="busy"
    fsm_state=FSMState.FOLLOW_LINE
    publish_status("TASK_RECEIVED")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


#-----QR system with visual feed-----
def draw_qr_overlay(frame, qr_objects, expected_id, match_found):
    """
    draw boxes + labels for detected QR codes on the frame
    """
    display_frame = frame.copy() #avoid modifying original frame
    
    for qr in qr_objects:
        # get QR code polygon points(corner points of QR code)
        points = qr.polygon
        if len(points) == 4:
            #convert to numpy array for drawing
            pts = np.array([[p.x, p.y] for p in points], np.int32)
            pts = pts.reshape((-1, 1, 2))

            #decode QR data to string using pyzbar
            qr_data = qr.data.decode("utf-8").strip()
            
            # green if match, Red if mismatch
            if qr_data == expected_id:
                color = (0, 255, 0)  # Green
                status = "MATCH!"
            else:
                color = (0, 0, 255)  # Red
                status = "MISMATCH"
            
            # draw polygon around QR
            cv2.polylines(display_frame, [pts], True, color, 3) # 3 for thickness
            
            # Draw QR data text
            x, y = points[0].x, points[0].y - 10
            cv2.putText(display_frame, f"{qr_data} - {status}", (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    return display_frame


def draw_status_overlay(frame, expected_id, elapsed_time, match_found):
    """
    Draw status information overlay on frame
    """
    #get frame dimensions
    height, width = frame.shape[:2]
    
    # Semi-transparent header background (HUD/ Heads-up display)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 80), (0, 0, 0), -1)
    frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)
    
    # Title
    cv2.putText(frame, "QR SCANNER - ROBOT CAM", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    # expected ID
    cv2.putText(frame, f"Looking for: {expected_id}", (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    
    # Timer
    remaining = max(0, QR_SCAN_TIMEOUT - elapsed_time)
    timer_color = (0, 255, 0) if remaining > 3 else (0, 0, 255)
    cv2.putText(frame, f"Time: {remaining:.1f}s", (10, 75),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, timer_color, 2)
    
    # Match status
    if match_found:
        cv2.putText(frame, "QR MATCHED!", (width - 200, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    
    # Instructions at bottom
    cv2.putText(frame, "Press 'Q' to cancel scan", (10, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
    return frame


def scan_qr_success():
    """
    QR scanning with VISUAL FEED using Pi Camera v3 + pyzbar
    Shows live camera feed with QR detection overlay
    """
    if not current_task or "container_id" not in current_task:
        publish_event("QR_ERROR", "No container_id in task")
        return False

    expected_id = str(current_task["container_id"])
    publish_event("QR_SCAN_START", expected_id)
    print(f"[QR] Starting scan - Looking for: {expected_id}")

    cam = Picamera2()
    cam.configure(
        cam.create_preview_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        )
    )
    cam.start()
    
    # Create window if visual feed enabled
    if SHOW_CAMERA_FEED:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, 800, 600)

    start_time = time.time()
    match_found = False
    matched_data = None
    
    try:
        while time.time() - start_time < QR_SCAN_TIMEOUT:
            frame = cam.capture_array()
            elapsed_time = time.time() - start_time
            
            # Convert to grayscale for QR detection
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            
            # Decode QR codes
            qr_codes = decode(gray)
            
            # Process detected QR codes
            for qr in qr_codes:
                qr_data = qr.data.decode("utf-8").strip()
                publish_event("QR_DETECTED", qr_data)
                print(f"[QR] Detected: {qr_data}")

                if qr_data == expected_id:
                    publish_event("QR_MATCH", qr_data)
                    print("[QR] MATCH CONFIRMED!")
                    match_found = True
                    matched_data = qr_data
                else:
                    publish_event("QR_MISMATCH", qr_data)
            
            # Visual Feed Display
            if SHOW_CAMERA_FEED:
                # Convert RGB to BGR for OpenCV display
                display_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                
                # Draw QR detection overlay
                display_frame = draw_qr_overlay(display_frame, qr_codes, expected_id, match_found)
                
                # Draw status overlay
                display_frame = draw_status_overlay(display_frame, expected_id, elapsed_time, match_found)
                
                # Show frame
                cv2.imshow(WINDOW_NAME, display_frame)
                
                # Check for key press (Q to quit, or any key if match found)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q'):
                    print("[QR] Scan cancelled by user")
                    publish_event("QR_CANCELLED")
                    return False
                
                # If match found, show success for a moment then return
                if match_found:
                    # Show success screen
                    success_frame = display_frame.copy()
                    cv2.rectangle(success_frame, (150, 200), (490, 280), (0, 255, 0), -1)
                    cv2.putText(success_frame, "QR MATCHED!", (180, 250),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
                    cv2.imshow(WINDOW_NAME, success_frame)
                    cv2.waitKey(1500)  # Show success for 1.5 seconds
                    return True
            
            else:
                # No visual feed - just check for match
                if match_found:
                    return True
            
            time.sleep(0.05)  # Small delay to reduce CPU usage

        # Timeout reached
        publish_event("QR_TIMEOUT")
        print("[QR] Scan timeout - no match found")
        
        if SHOW_CAMERA_FEED:
            # Show timeout message
            timeout_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(timeout_frame, "SCAN TIMEOUT", (180, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            cv2.putText(timeout_frame, f"Could not find: {expected_id}", (120, 290),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow(WINDOW_NAME, timeout_frame)
            cv2.waitKey(2000)
        
        return False

    except Exception as e:
        print(f"[QR] Error: {e}")
        publish_event("QR_ERROR", str(e))
        return False
        
    finally:
        cam.stop()
        if SHOW_CAMERA_FEED:
            cv2.destroyWindow(WINDOW_NAME)


# LIVE CAMERA FEED (STANDALONE) 

def show_live_feed(duration=30):
    """
    Show live camera feed without QR scanning
    Useful for testing/debugging camera positioning
    """
    print(f"[CAMERA] Starting live feed for {duration} seconds...")
    print("[CAMERA] Press 'Q' to quit, 'S' to take screenshot")
    
    cam = Picamera2()
    cam.configure(
        cam.create_preview_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        )
    )
    cam.start()
    
    cv2.namedWindow("Live Camera Feed", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Live Camera Feed", 800, 600)
    
    start_time = time.time()
    screenshot_count = 0
    
    try:
        while time.time() - start_time < duration:
            frame = cam.capture_array()
            display_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # Add timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(display_frame, timestamp, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Add instructions
            cv2.putText(display_frame, "Press Q to quit, S for screenshot", (10, 460),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            # Detect and show any QR codes
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            qr_codes = decode(gray)
            
            for qr in qr_codes:
                points = qr.polygon
                if len(points) == 4:
                    pts = np.array([[p.x, p.y] for p in points], np.int32)
                    cv2.polylines(display_frame, [pts.reshape((-1, 1, 2))], True, (0, 255, 0), 2)
                    qr_data = qr.data.decode("utf-8").strip()
                    cv2.putText(display_frame, qr_data, (points[0].x, points[0].y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            cv2.imshow("Live Camera Feed", display_frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == ord('Q'):
                break
            elif key == ord('s') or key == ord('S'):
                filename = f"screenshot_{screenshot_count}.jpg"
                cv2.imwrite(filename, display_frame)
                print(f"[CAMERA] Screenshot saved: {filename}")
                screenshot_count += 1
            
            time.sleep(0.03)
            
    finally:
        cam.stop()
        cv2.destroyAllWindows()
        print("[CAMERA] Live feed ended")


# ------FSM LOGIC ------

def detect_wide_black_patch():
    global wide_black_detected
    if wide_black_detected:
        wide_black_detected = False #reset flag before starting the FSM Loop
        return True
    return False


def fsm_loop():
    global fsm_state, wide_black_detected, align_done

    while not stop_flag:
        robot_state["fsm_state"] = fsm_state.value
        publish_status()

        if fsm_state == FSMState.IDLE:
            send_cmd("S")

        elif fsm_state == FSMState.FOLLOW_LINE:
            send_cmd("LF")
            publish_event("FOLLOWING_LINE")

            if detect_wide_black_patch():
                fsm_state = FSMState.AT_TARGET

        elif fsm_state == FSMState.AT_TARGET:
            send_cmd("S")
            publish_event("TARGET_REACHED")
            fsm_state = FSMState.SCAN_QR

        elif fsm_state == FSMState.SCAN_QR:
            if scan_qr_success():
                publish_event("QR_CONFIRMED")
                fsm_state = FSMState.ALIGN
            else:
                publish_event("QR_FAILED")
                fsm_state = FSMState.ERROR

        elif fsm_state == FSMState.ALIGN:
            send_cmd("ALIGN")
            publish_event("ALIGNED")
            fsm_state = FSMState.PICK_SIM

        elif fsm_state == FSMState.PICK_SIM:
            send_cmd("LED_RED_ON")
            send_cmd("BUZZER_ON")
            time.sleep(1)
            send_cmd("BUZZER_OFF")
            publish_event("PICK_COMPLETED")
            fsm_state = FSMState.DELIVER

        elif fsm_state == FSMState.DELIVER:
            send_cmd("LF")
            publish_event("DELIVERING")

            if detect_wide_black_patch():
                fsm_state = FSMState.DROP_SIM

        elif fsm_state == FSMState.DROP_SIM:
            send_cmd("LED_GREEN_ON")
            send_cmd("BUZZER_ON")
            time.sleep(1)
            send_cmd("BUZZER_OFF")
            send_cmd("LED_GREEN_OFF")

            publish_event("DROP_COMPLETED")

            robot_state["status"] = "idle"
            robot_state["task_id"] = None
            fsm_state = FSMState.IDLE

        elif fsm_state == FSMState.ERROR:
            send_cmd("S")
            publish_event("ERROR")
            time.sleep(2)
            fsm_state = FSMState.IDLE

        time.sleep(0.2)


#----- MAIN ------

def main():
    global stop_flag
    
    print("=" * 50)
    print(f"{ROBOT_NAME} starting (FSM mode)")
    print("=" * 50)
    
    # Check for test mode arguments
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test-camera":
            print("[TEST MODE] Camera feed test")
            show_live_feed(duration=60)
            return
        elif sys.argv[1] == "--test-qr":
            print("[TEST MODE] QR scan test")
            # Create dummy task for testing
            global current_task
            test_id = sys.argv[2] if len(sys.argv) > 2 else "TEST123"
            current_task = {"container_id": test_id, "task_id": "test"}
            robot_state["task_id"] = "test"
            result = scan_qr_success()
            print(f"[TEST] QR Scan result: {'SUCCESS' if result else 'FAILED'}")
            return

    connect_arduino()

    mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
    mqtt_client.subscribe(TOPIC_TASK_ASSIGN, 0)
    mqtt_client.loop_start()

    threading.Thread(target=arduino_listener, daemon=True).start()
    threading.Thread(target=fsm_loop, daemon=True).start()

    print("[SYSTEM] Robot ready - waiting for tasks")
    print("[TIP] Run with --test-camera to test camera feed")
    print("[TIP] Run with --test-qr <ID> to test QR scanning")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    stop_flag = True
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    send_cmd("S")
    cv2.destroyAllWindows()
    print("Robot stopped")


if __name__ == "__main__":
    main()






