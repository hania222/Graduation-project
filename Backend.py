"""
- Create and assign tasks
- Observe robot FSM state
- Log robot events
- Update task progress
- Serve data to Streamlit UI
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import paho.mqtt.client as mqtt
import json
from datetime import datetime
import threading

# Configuration
DATABASE = "warehouse.db"

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883

TOPIC_TASK_ASSIGN = "warehouse/tasks/assign"
TOPIC_ROBOT_STATUS = "warehouse/robot/status"
TOPIC_ROBOT_EVENTS = "warehouse/robot/events"



# Database helpers
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def query_db(query, args=(), one=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, args)

    if query.strip().upper().startswith("SELECT"):
        rows = cur.fetchall()
        conn.close()
        return rows[0] if (one and rows) else rows
    else:
        conn.commit()
        conn.close()


# MQTT setup
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected")
        client.subscribe([
            (TOPIC_ROBOT_STATUS, 0),
            (TOPIC_ROBOT_EVENTS, 0)
        ])
    else:
        print("[MQTT] Connection failed")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        print(f"[MQTT] {msg.topic} -> {data}")

        if msg.topic == TOPIC_ROBOT_STATUS:
            handle_robot_status(data)

        elif msg.topic == TOPIC_ROBOT_EVENTS:
            handle_robot_event(data)

    except Exception as e:
        print("[MQTT] Error:", e)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def start_mqtt():
    mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
    mqtt_client.loop_forever()


# Robot handlers
def handle_robot_status(data):
    """
    Expected:
    {
        robot_id,
        status,
        fsm_state,
        battery
    }
    """
    query_db("""
        UPDATE robots
        SET status=?, fsm_state=?, battery=?, last_seen=CURRENT_TIMESTAMP
        WHERE robot_id=?
    """, (
        data.get("status", "idle"),
        data.get("fsm_state", "IDLE"),
        data.get("battery", 100),
        data.get("robot_id")
    ))

def handle_robot_event(data):
    """
    Expected:
    {
        robot_id,
        task_id,
        event,
        details
    }
    """
    query_db("""
        INSERT INTO logs (robot_id, task_id, event, details)
        VALUES (?, ?, ?, ?)
    """, (
        data.get("robot_id"),
        data.get("task_id"),
        data.get("event"),
        data.get("details", "")
    ))

    # Update task step
    if data.get("task_id"):
        query_db("""
            UPDATE tasks
            SET current_step=?
            WHERE task_id=?
        """, (
            data.get("event"),
            data.get("task_id")
        ))

    # Complete task
    if data.get("event") == "DROP_COMPLETED":
        query_db("""
            UPDATE tasks
            SET status='completed', completed_at=CURRENT_TIMESTAMP
            WHERE task_id=?
        """, (data.get("task_id"),))


# Flask App
app = Flask(__name__)
CORS(app)

# HTTP Endpoints
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "mqtt_connected": mqtt_client.is_connected(),
        "time": datetime.now().isoformat()
    })

@app.route("/robots")
def get_robots():
    robots = query_db("SELECT * FROM robots")
    return jsonify([dict(r) for r in robots])

@app.route("/tasks")
def get_tasks():
    tasks = query_db("SELECT * FROM tasks ORDER BY created_at DESC")
    return jsonify([dict(t) for t in tasks])

@app.route("/logs")
def get_logs():
    logs = query_db("""
        SELECT * FROM logs
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    return jsonify([dict(l) for l in logs])

@app.route("/tasks/create", methods=["POST"])
def create_task():
    """
    Body:
    {
        container_id,
        action: PICK | DROP,
        source_rack,
        destination_rack
    }
    """
    data = request.get_json()

    query_db("""
        INSERT INTO tasks (container_id, action, source_rack, destination_rack)
        VALUES (?, ?, ?, ?)
    """, (
        data["container_id"],
        data["action"],
        data.get("source_rack"),
        data.get("destination_rack")
    ))

    task = query_db(
        "SELECT * FROM tasks ORDER BY task_id DESC LIMIT 1",
        one=True
    )

    mqtt_client.publish(TOPIC_TASK_ASSIGN, json.dumps(dict(task)))

    return jsonify({
        "message": "Task created and assigned",
        "task": dict(task)
    })



if __name__ == "__main__":
    print("=" * 50)
    print("Warehouse Backend Starting")
    print("=" * 50)

    mqtt_thread = threading.Thread(target=start_mqtt)
    mqtt_thread.daemon = True
    mqtt_thread.start()

    app.run(host="0.0.0.0", port=5000, debug=False)
