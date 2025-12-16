"""
mqtt+HTTP protocols API backend
- uses SQLite DB (warehouse1.db).
- exposes HTTP endpoints for Streamlit UI to create tasks and query DB.
- Publishes new tasks to MQTT topic warehouse/tasks.
- Subscribes to warehouse/robot/logs and warehouse/robot/status and writes
  incoming messages into the logs table and updates robots/tasks status.

Requirements:
pip install flask flask-cors paho-mqtt
Run:
python mqtt_backend.py
(Ensure an MQTT broker is available at BROKER_HOST:BROKER_PORT - e.g., Mosquitto on the same Pi)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import paho.mqtt.client as mqtt
import json
from datetime import datetime
import threading

# Configuration
DATABASE = "warehouse1.db"
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC_TASKS = "warehouse/tasks"
TOPIC_LOGS = "warehouse/robot/logs"
TOPIC_STATUS = "warehouse/robot/status"

# Create Flask app and enable CORS
app = Flask(__name__)
CORS(app)


def get_db_connection():
    """Create a new database connection for the current thread"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def query_db(query, args=(), one=False):
    """Helper function to run queries against the database"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, args)
    
    if query.strip().upper().startswith("SELECT"):
        rows = cur.fetchall()
        conn.close()
        return (rows[0] if rows else None) if one else rows
    else:
        conn.commit()
        conn.close()
        return None


def init_db():
    """Create tables if they don't exist"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create robots table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS robots (
            robot_id INTEGER PRIMARY KEY,
            name TEXT DEFAULT 'Robot',
            status TEXT DEFAULT 'idle',
            battery INTEGER DEFAULT 100,
            x_pos INTEGER DEFAULT 0,
            y_pos INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create tasks table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER,
            action TEXT DEFAULT 'Pick',
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            assigned_robot INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (assigned_robot) REFERENCES robots(robot_id)
        )
    ''')
    
    # Create logs table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot_id INTEGER,
            task_id INTEGER,
            message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (robot_id) REFERENCES robots(robot_id),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    ''')
    
    # Create inventory table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER UNIQUE,
            item_name TEXT,
            quantity INTEGER DEFAULT 0,
            status TEXT DEFAULT 'available',
            location TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default robot if none exists
    cur.execute('SELECT COUNT(*) FROM robots')
    if cur.fetchone()[0] == 0:
        cur.execute('''
            INSERT INTO robots (robot_id, name, status, battery, x_pos, y_pos) 
            VALUES (1, 'Robot-01', 'idle', 100, 0, 0)
        ''')
        print("[DB] Default robot created")
    
    # Insert sample inventory if none exists
    cur.execute('SELECT COUNT(*) FROM inventory')
    if cur.fetchone()[0] == 0:
        sample_inventory = [
            (1001, 'Widget A', 50, 'available', 'A1'),
            (1002, 'Widget B', 30, 'available', 'A2'),
            (1003, 'Gadget C', 25, 'available', 'B1'),
            (1004, 'Gadget D', 40, 'available', 'B2'),
            (1005, 'Part E', 100, 'available', 'C1'),
        ]
        cur.executemany('''
            INSERT INTO inventory (container_id, item_name, quantity, status, location)
            VALUES (?, ?, ?, ?, ?)
        ''', sample_inventory)
        print("[DB] Sample inventory created")
    
    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully")


# MQTT Client Setup
mqtt_client = mqtt.Client()


def on_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects to broker"""
    if rc == 0:
        print("[MQTT] Connected to broker successfully")
        client.subscribe([(TOPIC_LOGS, 0), (TOPIC_STATUS, 0)])
        print(f"[MQTT] Subscribed to {TOPIC_LOGS} and {TOPIC_STATUS}")
    else:
        print(f"[MQTT] Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """Callback when a message is received from subscribed topics"""
    try:
        data = json.loads(msg.payload.decode())
        print(f"[MQTT] Received on {msg.topic}: {data}")
        
        # Handle robot logs
        if msg.topic == TOPIC_LOGS:
            timestamp = datetime.fromtimestamp(data.get("timestamp", datetime.now().timestamp()))
            query_db(
                "INSERT INTO logs (robot_id, task_id, message, timestamp) VALUES (?, ?, ?, ?)",
                (data.get("robot_id"),
                 data.get("task_id"),
                 data.get("message", ""),
                 timestamp)
            )
            print(f"[DB] Log inserted from robot {data.get('robot_id')}")
        
        # Handle robot status updates
        elif msg.topic == TOPIC_STATUS:
            robot_id = data.get("robot_id")
            status = data.get("status", "idle")
            battery = data.get("battery", 100)
            x_pos = data.get("x_pos", 0)
            y_pos = data.get("y_pos", 0)
            task_id = data.get("task_id")
            
            # Check if robot exists, if not create it
            existing = query_db("SELECT * FROM robots WHERE robot_id=?", (robot_id,), one=True)
            if existing:
                query_db(
                    "UPDATE robots SET status=?, battery=?, x_pos=?, y_pos=?, last_updated=? WHERE robot_id=?",
                    (status, battery, x_pos, y_pos, datetime.now(), robot_id)
                )
            else:
                query_db(
                    "INSERT INTO robots (robot_id, name, status, battery, x_pos, y_pos) VALUES (?, ?, ?, ?, ?, ?)",
                    (robot_id, f"Robot-{robot_id:02d}", status, battery, x_pos, y_pos)
                )
            
            print(f"[DB] Robot {robot_id} status updated: {status}")
            
            # Mark task as completed if status indicates completion
            if task_id and status == "completed":
                query_db(
                    "UPDATE tasks SET status='completed', completed_at=? WHERE task_id=?",
                    (datetime.now(), task_id)
                )
                print(f"[DB] Task {task_id} marked as completed")
            
            # Handle QR confirmed event
            if data.get("event") == "QR_CONFIRMED":
                log_message = f"QR Code confirmed at position ({x_pos}, {y_pos})"
                query_db(
                    "INSERT INTO logs (robot_id, task_id, message, timestamp) VALUES (?, ?, ?, ?)",
                    (robot_id, task_id, log_message, datetime.now())
                )
                print(f"[DB] QR confirmation logged for robot {robot_id}")
                
    except json.JSONDecodeError as e:
        print(f"[MQTT] JSON decode error: {e}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")


def on_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects"""
    print(f"[MQTT] Disconnected with code {rc}")
    if rc != 0:
        print("[MQTT] Unexpected disconnection, attempting to reconnect...")


# Set MQTT callbacks
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.on_disconnect = on_disconnect


def connect_mqtt():
    """Connect to MQTT broker with retry logic"""
    try:
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        mqtt_client.loop_start()
        print("[MQTT] Client loop started")
    except Exception as e:
        print(f"[MQTT] Failed to connect to broker: {e}")
        print("[MQTT] Make sure Mosquitto is running: sudo systemctl start mosquitto")


# HTTP Endpoints
@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "mqtt_connected": mqtt_client.is_connected(),
        "timestamp": datetime.now().isoformat()
    })


@app.route("/dashboard")
def dashboard():
    """Dashboard summary data"""
    try:
        total_inventory = query_db("SELECT COUNT(*) AS c FROM inventory", one=True)
        total_tasks = query_db("SELECT COUNT(*) AS c FROM tasks", one=True)
        completed_tasks = query_db("SELECT COUNT(*) AS c FROM tasks WHERE status='completed'", one=True)
        pending_tasks = query_db("SELECT COUNT(*) AS c FROM tasks WHERE status='pending'", one=True)
        robots = query_db("SELECT * FROM robots")
        
        return jsonify({
            "total_inventory": total_inventory["c"] if total_inventory else 0,
            "total_tasks": total_tasks["c"] if total_tasks else 0,
            "completed_tasks": completed_tasks["c"] if completed_tasks else 0,
            "pending_tasks": pending_tasks["c"] if pending_tasks else 0,
            "robots": [dict(r) for r in robots] if robots else []
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inventory")
def inventory():
    """Get all inventory items"""
    try:
        items = query_db("SELECT * FROM inventory")
        return jsonify([dict(i) for i in items] if items else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inventory/add", methods=["POST"])
def add_inventory():
    """Add a new inventory item"""
    try:
        data = request.get_json()
        query_db(
            "INSERT INTO inventory (container_id, item_name, quantity, status, location) VALUES (?, ?, ?, ?, ?)",
            (data["container_id"], data.get("item_name", ""), 
             data.get("quantity", 0), data.get("status", "available"), 
             data.get("location", ""))
        )
        return jsonify({"message": "Inventory item added"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Container ID already exists"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tasks", methods=["GET"])
def get_tasks():
    """Get all tasks"""
    try:
        tasks = query_db("SELECT * FROM tasks ORDER BY created_at DESC")
        return jsonify([dict(t) for t in tasks] if tasks else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tasks/create", methods=["POST"])
def create_task():
    """Create a new task and publish to MQTT"""
    try:
        data = request.get_json()
        
        # Insert task into database
        query_db(
            "INSERT INTO tasks (container_id, action, priority, status) VALUES (?, ?, ?, 'pending')",
            (data["container_id"], data.get("action", "Pick"), data.get("priority", 1))
        )
        
        # Get the newly created task
        task = query_db("SELECT * FROM tasks ORDER BY task_id DESC LIMIT 1", one=True)
        
        if task:
            task_dict = dict(task)
            # Publish task to MQTT for robots
            mqtt_client.publish(TOPIC_TASKS, json.dumps(task_dict))
            print(f"[MQTT] Task {task_dict['task_id']} published to {TOPIC_TASKS}")
            
            return jsonify({"message": "Task created", "task": task_dict}), 201
        else:
            return jsonify({"error": "Failed to create task"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tasks/<int:task_id>/update", methods=["PUT"])
def update_task(task_id):
    """Update task status"""
    try:
        data = request.get_json()
        status = data.get("status")
        
        if status == "completed":
            query_db(
                "UPDATE tasks SET status=?, completed_at=? WHERE task_id=?",
                (status, datetime.now(), task_id)
            )
        else:
            query_db(
                "UPDATE tasks SET status=? WHERE task_id=?",
                (status, task_id)
            )
        
        return jsonify({"message": f"Task {task_id} updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/robots")
def robots():
    """Get all robots"""
    try:
        robot_list = query_db("SELECT * FROM robots")
        return jsonify([dict(r) for r in robot_list] if robot_list else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/robots/<int:robot_id>")
def get_robot(robot_id):
    """Get specific robot by ID"""
    try:
        robot = query_db("SELECT * FROM robots WHERE robot_id=?", (robot_id,), one=True)
        if robot:
            return jsonify(dict(robot))
        return jsonify({"error": "Robot not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logs")
def logs():
    """Get all logs"""
    try:
        log_list = query_db("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 100")
        return jsonify([dict(l) for l in log_list] if log_list else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logs/robot/<int:robot_id>")
def robot_logs(robot_id):
    """Get logs for specific robot"""
    try:
        log_list = query_db(
            "SELECT * FROM logs WHERE robot_id=? ORDER BY timestamp DESC LIMIT 50",
            (robot_id,)
        )
        return jsonify([dict(l) for l in log_list] if log_list else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Main entry point
if _name_ == "_main_":
    print("=" * 50)
    print("Warehouse Backend Starting...")
    print("=" * 50)
    
    # Initialize database
    init_db()
    
    # Connect to MQTT broker
    connect_mqtt()
    
    # Start Flask server
    print(f"[HTTP] Starting server on http://0.0.0.0:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)