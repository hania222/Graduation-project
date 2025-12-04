
import sqlite3
def init_db():
    conn = sqlite3.connect("warehouse.db")
    cursor = conn.cursor()

    # Inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        container_id INTEGER PRIMARY KEY,
        rack_id TEXT,
        item_name TEXT,
        quantity INTEGER,
        weight REAL,
        dimensions TEXT,
        status TEXT DEFAULT 'available'
    )
    """)

    

    # Robots table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS robots (
        robot_id INTEGER PRIMARY KEY,
        name TEXT,
        battery INTEGER DEFAULT 100,
        x_pos INTEGER DEFAULT 0,
        y_pos INTEGER DEFAULT 0,
        current_container INTEGER,
        status TEXT DEFAULT 'idle'
    )
    """)

    # Tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY,
        robot_id INTEGER,
        container_id INTEGER,
        action TEXT,
        priority INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP
    )
    """)

    # Racks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS racks (
        rack_id TEXT PRIMARY KEY,
        max_capacity INTEGER,
        current_capacity INTEGER DEFAULT 0
    )
    """)

    # Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        log_id INTEGER PRIMARY KEY,
        robot_id INTEGER,
        task_id INTEGER,
        message TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Initialize some robots
    robots = [("Robot-1",), ("Robot-2",), ("Robot-3",)]
    cursor.executemany("""
    INSERT OR IGNORE INTO robots (name) VALUES (?)
    """, robots)

 #save and close
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
