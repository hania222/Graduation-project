import sqlite3

DATABASE = "warehouse1.db"

def get_connection():
    conn = sqlite3.connect(DATABASE)
    return conn

def clear_logs():
    """Delete all logs"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM logs")
    conn.commit()
    conn.close()
    print("[DB] All logs cleared")

def clear_tasks():
    """Delete all tasks"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()
    print("[DB] All tasks cleared")

def reset_robots():
    """Reset robot table to default robot"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM robots")
    # Insert default robot
    cur.execute('''
        INSERT INTO robots (robot_id, name, status, battery, x_pos, y_pos)
        VALUES (1, 'Robot-01', 'idle', 100, 0, 0)
    ''')
    conn.commit()
    conn.close()
    print("[DB] Robots reset to default")

def clear_inventory():
    """Delete all inventory items"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory")
    conn.commit()
    conn.close()
    print("[DB] Inventory cleared")

def main():
    print("Select what you want to clear/reset:")
    print("1 - Logs")
    print("2 - Tasks")
    print("3 - Robots (reset to default)")
    print("4 - Inventory")
    print("5 - Everything")
    
    choice = input("Enter choice (1-5): ").strip()
    
    if choice == "1":
        clear_logs()
    elif choice == "2":
        clear_tasks()
    elif choice == "3":
        reset_robots()
    elif choice == "4":
        clear_inventory()
    elif choice == "5":
        clear_logs()
        clear_tasks()
        reset_robots()
        clear_inventory()
        print("[DB] Everything cleared/reset")
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
