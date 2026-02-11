import sqlite3

DATABASE = "warehouse.db"

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

  
    # Robots table 
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS robots (
        robot_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'idle',
        fsm_state TEXT DEFAULT 'IDLE',
        battery INTEGER DEFAULT 100,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)


    # Inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        container_id INTEGER PRIMARY KEY,
        rack_id TEXT,
        item_name TEXT,
        quantity INTEGER DEFAULT 0,
        status TEXT DEFAULT 'stored'
    )
    """)


    # Tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_id INTEGER,
        action TEXT CHECK(action IN ('PICK','DROP')),
        source_rack TEXT,
        destination_rack TEXT,
        status TEXT DEFAULT 'pending',
        current_step TEXT DEFAULT 'WAITING',
        assigned_robot INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (container_id) REFERENCES inventory(container_id),
        FOREIGN KEY (assigned_robot) REFERENCES robots(robot_id)
    )
    """)


    # Logs/events table 
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        robot_id INTEGER,
        task_id INTEGER,
        event TEXT,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    
    # Default robot
    cursor.execute("""
    INSERT OR IGNORE INTO robots (robot_id, name)
    VALUES (1, 'Robot-01')
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully")

if __name__ == "__main__":
    init_db()
