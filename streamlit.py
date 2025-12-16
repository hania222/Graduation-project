"""
streamlit_app.py
- Streamlit dashboard for warehouse management
- Connects to Flask backend via HTTP

Requirements:
pip install streamlit pandas requests

Run:
streamlit run streamlit_app.py
"""

import streamlit as st
import pandas as pd
import requests
import time

# Backend Configuration
BACKEND_URL = "http://127.0.0.1:5000"


# Helper Functions with Error Handling
def safe_request(endpoint, method="GET", json_data=None, timeout=5):
    """Make HTTP request with error handling"""
    try:
        url = f"{BACKEND_URL}{endpoint}"
        if method == "GET":
            response = requests.get(url, timeout=timeout)
        elif method == "POST":
            response = requests.post(url, json=json_data, timeout=timeout)
        elif method == "PUT":
            response = requests.put(url, json=json_data, timeout=timeout)
        else:
            return None
        
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to backend! Make sure mqtt_backend.py is running.")
        return None
    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. Backend may be overloaded.")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ HTTP Error: {e}")
        return None
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        return None


def get_dashboard():
    """Fetch dashboard data"""
    return safe_request("/dashboard")


def get_inventory():
    """Fetch inventory data"""
    return safe_request("/inventory")


def get_tasks():
    """Fetch tasks data"""
    return safe_request("/tasks")


def get_robots():
    """Fetch robots data"""
    return safe_request("/robots")


def get_logs():
    """Fetch logs data"""
    return safe_request("/logs")


def create_task(container_id, action, priority):
    """Create a new task"""
    payload = {
        "container_id": container_id,
        "action": action,
        "priority": priority
    }
    return safe_request("/tasks/create", method="POST", json_data=payload)


def add_inventory_item(container_id, item_name, quantity, location):
    """Add a new inventory item"""
    payload = {
        "container_id": container_id,
        "item_name": item_name,
        "quantity": quantity,
        "location": location,
        "status": "available"
    }
    return safe_request("/inventory/add", method="POST", json_data=payload)


def check_backend_health():
    """Check if backend is running"""
    result = safe_request("/health")
    return result is not None


# Page Configuration
st.set_page_config(
    page_title="Smart Warehouse Dashboard",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .status-idle { color: #808080; }
    .status-busy { color: #ffa500; }
    .status-completed { color: #00ff00; }
    .status-error { color: #ff0000; }
</style>
""", unsafe_allow_html=True)

# Title
st.title("🏭 Smart Warehouse Dashboard")

# Sidebar
with st.sidebar:
    st.header("⚙ Settings")
    
    # Backend status
    st.subheader("Backend Status")
    if check_backend_health():
        st.success("✅ Backend Connected")
    else:
        st.error("❌ Backend Disconnected")
        st.info("Run: python mqtt_backend.py")
    
    # Auto-refresh
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)
    if auto_refresh:
        time.sleep(5)
        st.rerun()
    
    # Manual refresh button
    if st.button("🔄 Refresh Now"):
        st.rerun()

# Create tabs
tabs = st.tabs(["📊 Dashboard", "📦 Inventory", "🤖 Robots", "📋 Tasks", "➕ Create Task", "📜 Logs"])

# Dashboard Tab
with tabs[0]:
    st.header("Overview")
    
    data = get_dashboard()
    
    if data:
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="📦 Total Inventory",
                value=data.get("total_inventory", 0)
            )
        
        with col2:
            st.metric(
                label="📋 Total Tasks",
                value=data.get("total_tasks", 0)
            )
        
        with col3:
            st.metric(
                label="✅ Completed Tasks",
                value=data.get("completed_tasks", 0)
            )
        
        with col4:
            st.metric(
                label="⏳ Pending Tasks",
                value=data.get("pending_tasks", 0)
            )
        
        st.divider()
        
        # Robots status
        st.subheader("🤖 Robots Status")
        robots = data.get("robots", [])
        
        if robots:
            robot_df = pd.DataFrame(robots)
            
            # Display robot cards
            cols = st.columns(min(len(robots), 4))
            for i, robot in enumerate(robots):
                with cols[i % 4]:
                    status_color = {
                        "idle": "🟢",
                        "busy": "🟡",
                        "error": "🔴",
                        "completed": "🟢"
                    }.get(robot.get("status", "idle"), "⚪")
                    
                    st.markdown(f"""
                    *{robot.get('name', f'Robot {robot.get("robot_id")}')}* {status_color}
                    - Status: {robot.get('status', 'unknown')}
                    - Battery: {robot.get('battery', 0)}%
                    - Position: ({robot.get('x_pos', 0)}, {robot.get('y_pos', 0)})
                    """)
            
            st.divider()
            st.dataframe(robot_df, use_container_width=True)
        else:
            st.info("No robots registered yet.")
    else:
        st.warning("Unable to fetch dashboard data. Check backend connection.")

# Inventory Tab
with tabs[1]:
    st.header("📦 Inventory Management")
    
    inventory = get_inventory()
    
    if inventory:
        df = pd.DataFrame(inventory)
        
        # Summary
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Items", len(df))
        with col2:
            available = len(df[df['status'] == 'available']) if 'status' in df.columns else 0
            st.metric("Available", available)
        with col3:
            total_qty = df['quantity'].sum() if 'quantity' in df.columns else 0
            st.metric("Total Quantity", total_qty)
        
        st.divider()
        
        # Filter
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "available", "reserved", "picked"],
            key="inventory_filter"
        )
        
        if status_filter != "All":
            df = df[df['status'] == status_filter]
        
        st.dataframe(df, use_container_width=True)
        
        # Add new inventory item
        st.divider()
        st.subheader("➕ Add Inventory Item")
        
        with st.form("add_inventory_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_container_id = st.number_input("Container ID", min_value=1, step=1)
                new_item_name = st.text_input("Item Name")
            with col2:
                new_quantity = st.number_input("Quantity", min_value=0, step=1)
                new_location = st.text_input("Location (e.g., A1, B2)")
            
            if st.form_submit_button("Add Item"):
                result = add_inventory_item(new_container_id, new_item_name, new_quantity, new_location)
                if result and "error" not in result:
                    st.success("✅ Item added successfully!")
                    st.rerun()
                elif result:
                    st.error(f"Failed to add item: {result.get('error')}")
    else:
        st.info("No inventory items found or unable to fetch data.")

# Robots Tab
with tabs[2]:
    st.header("🤖 Robot Fleet")
    
    robots = get_robots()
    
    if robots:
        df = pd.DataFrame(robots)
        
        # Robot cards
        for robot in robots:
            with st.expander(f"🤖 {robot.get('name', f'Robot {robot.get(\"robot_id\")}')} - {robot.get('status', 'unknown').upper()}"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Battery", f"{robot.get('battery', 0)}%")
                
                with col2:
                    st.metric("X Position", robot.get('x_pos', 0))
                
                with col3:
                    st.metric("Y Position", robot.get('y_pos', 0))
                
                st.text(f"Last Updated: {robot.get('last_updated', 'N/A')}")
        
        st.divider()
        st.subheader("Full Robot Data")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No robots found or unable to fetch data.")

# Tasks Tab
with tabs[3]:
    st.header("📋 Task Management")
    
    tasks = get_tasks()
    
    if tasks:
        df = pd.DataFrame(tasks)
        
        # Summary
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total", len(df))
        with col2:
            pending = len(df[df['status'] == 'pending']) if 'status' in df.columns else 0
            st.metric("Pending", pending)
        with col3:
            in_progress = len(df[df['status'] == 'in_progress']) if 'status' in df.columns else 0
            st.metric("In Progress", in_progress)
        with col4:
            completed = len(df[df['status'] == 'completed']) if 'status' in df.columns else 0
            st.metric("Completed", completed)
        
        st.divider()
        
        # Filter
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "pending", "in_progress", "completed", "failed"],
            key="task_filter"
        )
        
        if status_filter != "All":
            df = df[df['status'] == status_filter]
        
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No tasks found or unable to fetch data.")

# Create Task Tab
with tabs[4]:
    st.header("➕ Create New Task")
    
    inventory = get_inventory()
    
    if inventory:
        # Filter only available items
        available_items = [item for item in inventory if item.get("status") == "available"]
        
        if available_items:
            inventory_options = {
                f"{item['container_id']} - {item.get('item_name', 'Unknown')} ({item.get('location', 'N/A')})": item["container_id"]
                for item in available_items
            }
            
            with st.form("create_task_form"):
                st.subheader("Task Details")
                
                selected_container = st.selectbox(
                    "Select Container",
                    options=list(inventory_options.keys()),
                    help="Choose a container from available inventory"
                )
                
                col1, col2 = st.columns(2)
                
                with col1:
                    action = st.selectbox(
                        "Action",
                        ["Pick", "Place", "Move", "Scan"],
                        help="Select the action for the robot to perform"
                    )
                
                with col2:
                    priority = st.selectbox(
                        "Priority",
                        [1, 2, 3, 4, 5],
                        help="1 = Highest priority, 5 = Lowest priority"
                    )
                
                submitted = st.form_submit_button("🚀 Create Task", use_container_width=True)
                
                if submitted:
                    container_id = inventory_options[selected_container]
                    response = create_task(container_id, action, priority)
                    
                    if response and "task" in response:
                        st.success(f"✅ Task #{response['task']['task_id']} created successfully!")
                        st.json(response['task'])
                    elif response:
                        st.error(f"Failed to create task: {response.get('error', 'Unknown error')}")
        else:
            st.warning("⚠ No available inventory items. Add inventory first.")
    else:
        st.error("Unable to fetch inventory data.")

# Logs Tab
with tabs[5]:
    st.header("📜 System Logs")
    
    logs = get_logs()
    
    if logs:
        df = pd.DataFrame(logs)
        
        # Filter by robot
        robots = get_robots()
        robot_ids = ["All"] + [str(r.get("robot_id")) for r in (robots or [])]
        
        selected_robot = st.selectbox("Filter by Robot", robot_ids, key="log_robot_filter")
        
        if selected_robot != "All":
            df = df[df['robot_id'] == int(selected_robot)]
        
        # Display logs
        st.dataframe(df, use_container_width=True)
        
        # Recent activity
        st.divider()
        st.subheader("📌 Recent Activity")
        
        for _, log in df.head(10).iterrows():
            timestamp = log.get('timestamp', 'N/A')
            robot_id = log.get('robot_id', 'N/A')
            message = log.get('message', 'No message')
            
            st.text(f"[{timestamp}] Robot {robot_id}: {message}")
    else:
        st.info("No logs found or unable to fetch data.")

# Footer
st.divider()
st.caption("🏭 Smart Warehouse Management System | Built with Streamlit & Flask")