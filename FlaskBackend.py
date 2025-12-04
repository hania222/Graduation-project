'''
-Flask--> creates the web server app
-request--> handles incoming requests
-jsonify-->converts python objects into JSON responses
'''
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime
import random

app = Flask(__name__)  # Create Flask app object
CORS(app)              # Allow connection from Streamlit
DATABASE = "warehouse.db"

''' Helper Function --> to run queries against the database '''
def query_db(query, args=(), one=False):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # To return rows as dictionaries
    cur = conn.cursor()
    cur.execute(query, args)
    rows = cur.fetchall()          #read results for the SELECT queries
    conn.commit()                 
    conn.close()
    return (rows[0] if rows else None) if one else rows

#Routes:
# Dashboard 
@app.route('/dashboard')
def dashboard():
    stats = {
        "total_inventory": query_db("SELECT COUNT(*) AS c FROM inventory", one=True)["c"],
        "total_tasks": query_db("SELECT COUNT(*) AS c FROM tasks", one=True)["c"],
        "completed_tasks": query_db("SELECT COUNT(*) AS c FROM tasks WHERE status='completed'", one=True)["c"],
        "pending_tasks": query_db("SELECT COUNT(*) AS c FROM tasks WHERE status='pending'", one=True)["c"],
        "robots": [dict(r) for r in query_db("SELECT * FROM robots")]  
    }
    return jsonify(stats)

#  Inventory
@app.route('/inventory', methods=['GET'])
def get_inventory():
    inventory = query_db("SELECT * FROM inventory")
    return jsonify([dict(i) for i in inventory])


@app.route('/inventory', methods=['POST'])
def add_inventory():
    data = request.get_json()
    query_db("""
        INSERT INTO inventory (container_id, rack_id, item_name, quantity, weight, dimensions)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        data['container_id'],
        data['rack_id'],
        data.get('item_name', ''),
        data['quantity'],
        data.get('weight', 0),
        data.get('dimensions', '')
    ))
    return jsonify({"message": "Inventory added"}), 201



@app.route('/inventory/<int:container_id>', methods=['PUT'])
def update_inventory(container_id):
    data = request.get_json()
    query_db("UPDATE inventory SET quantity=?, status=? WHERE container_id=?",
             (data['quantity'], data.get('status', 'available'), container_id))
    return jsonify({"message": "Inventory updated"})

#  Tasks
@app.route('/tasks', methods=['GET'])
def get_tasks():
    tasks = query_db("""
        SELECT t.task_id, r.name AS robot, i.item_name AS tray, t.action, t.status
        FROM tasks t
        LEFT JOIN robots r ON t.robot_id=r.robot_id
        LEFT JOIN inventory i ON t.container_id=i.container_id
    """)
    return jsonify([dict(t) for t in tasks])

@app.route('/tasks', methods=['POST'])
def add_task():
    data = request.get_json()
    query_db("""
        INSERT INTO tasks (robot_id, container_id, action, priority)
        VALUES (?, ?, ?, ?)
    """, (None, data['container_id'], data['action'], data.get('priority', 1)))
    return jsonify({"message": "Task added"}), 201

@app.route('/tasks/update', methods=['PUT'])
def update_task():
    data = request.get_json()
    query_db("UPDATE tasks SET status=?, started_at=?, completed_at=? WHERE task_id=?",
             (data['status'],
              data.get('started_at'),
              data.get('completed_at'),
              data['task_id']))
    return jsonify({"message": "Task updated"})

@app.route('/tasks/delete_completed', methods=['DELETE'])
def delete_completed_tasks():
    query_db("DELETE FROM tasks WHERE status='completed'")
    return jsonify({"message": "All completed tasks deleted"})

# Scheduler Simulation
@app.route('/scheduler/run', methods=['POST'])
def run_scheduler():
    # Get pending tasks FIFO
    tasks = query_db("SELECT * FROM tasks WHERE status='pending' ORDER BY priority, created_at")
    robots = query_db("SELECT * FROM robots WHERE status='idle'")

    for task in tasks:
        if not robots:
            break  # No available robots
        robot = robots.pop(0)
        # Assign robot
        query_db("UPDATE tasks SET robot_id=?, status=?, started_at=? WHERE task_id=?",
                 (robot['robot_id'], 'in_progress', datetime.now(), task['task_id']))
        # Update robot status
        query_db("UPDATE robots SET status='moving', current_container=? WHERE robot_id=?",
                 (task['container_id'], robot['robot_id']))
    return jsonify({"message": "Scheduler executed"})

#robot simulation 
@app.route('/robots/simulate', methods=['POST'])
def simulate_robots():
    robots = query_db("SELECT * FROM robots")
    for r in robots:
        # randomly simulate battery decrease
        battery = max(0, r['battery'] - random.randint(1,5))
        status = 'idle' if battery < 10 else r['status']
        query_db("UPDATE robots SET battery=?, status=? WHERE robot_id=?",
                 (battery, status, r['robot_id']))
    return jsonify({"message": "Robots simulated"})

#Logs (like a history for debugging problems later)
@app.route('/logs', methods=['GET'])
def get_logs():
    logs = query_db("SELECT * FROM logs ORDER BY timestamp DESC")
    return jsonify([dict(l) for l in logs])

# Main
if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5000, debug=True)
