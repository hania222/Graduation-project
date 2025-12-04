import streamlit as st
import requests
import pandas as pd

API_URL = "http://127.0.0.1:5000"

# Page setup
st.set_page_config(
    page_title="🤖 Smart Warehouse System",
    layout="wide",
    page_icon="🏭"
)



# sidebar with icons 
menu = st.sidebar.radio("Navigation", [
    "🏠 Dashboard",
    "📦 Inventory",
    "🤖 Tasks",
    "⚙️ Scheduler",
    "🚀 Robots"
])

# Dashboard 
if menu == "🏠 Dashboard":
    st.title("🏭 Smart Warehouse Dashboard")
    res = requests.get(f"{API_URL}/dashboard").json() #calls flask endpoint that named dashboard
    
   #create 4 columns to display the metrics
    cols = st.columns(4)
    cols[0].metric("Total Containers", res["total_inventory"])
    cols[1].metric("Total Tasks", res["total_tasks"])
    cols[2].metric("Completed Tasks", res["completed_tasks"])
    cols[3].metric("Pending Tasks", res["pending_tasks"])
    

    st.subheader("Robots Status")
    df_robots = pd.DataFrame(res["robots"])
    st.dataframe(df_robots)

# inventory
elif menu == "📦 Inventory":
    #st.title("📦 Container Management")
    st.markdown("<h1 style='margin-bottom: -10px;'>📦 Container Management</h1>", unsafe_allow_html=True)
    st.write("Manage all warehouse containers efficiently with real-time updates.")

    tab1, tab2 = st.tabs(["➕ Add Container", "📋 View / Update Containers"])

    racks_list = ["A1","A2","A3","B1","B2","B3","C1","C2","C3"]
    containers_list = [f"container #{i}" for i in range(101, 111)]  # example 10 containers

    # Add Container
    with tab1:
        container_name = st.selectbox("Select Container", containers_list)
        rack = st.selectbox("Select Rack", racks_list)
        item_name = st.text_input("Item Name")
        quantity = st.number_input("Quantity", min_value=0)
        if st.button("Add Container"):
            container_id = int(container_name.split("#")[1])
            requests.post(f"{API_URL}/inventory", json={
                "container_id": container_id,
                "rack_id": rack,
                "item_name": item_name,
                "quantity": quantity
            })
            st.success(f"{container_name} added to {rack}")
            st.success("✔ Operation Completed Successfully")
            st.warning("⚠ Please check the input")


    # View / Update
    with tab2:
        df = pd.DataFrame(requests.get(f"{API_URL}/inventory").json())
        st.dataframe(df)
        st.write("Update Container Quantity / Status")
        container_id = [f"container #{i['container_id']}" for i in df.to_dict('records')]
        selected_container = st.selectbox("Select Container", container_id)
        new_quantity = st.number_input("New Quantity", min_value=0)
        new_status = st.selectbox("Status", ["available", "reserved", "picked"])
        if st.button("Update Container"):
            container_id = int(selected_container.split("#")[1])
            requests.put(f"{API_URL}/inventory/{container_id}", json={
                "quantity": new_quantity,
                "status": new_status
            })
            st.success(f"{selected_container} updated successfully")
            st.success("✔ Operation Completed Successfully")
            st.warning("⚠ Please check the input")


# Tasks 
elif menu == "🤖 Tasks":
    st.title("🤖 Task Management")
    tab1, tab2, tab3, tab4 = st.tabs([
        "🆕 Add Task",
        "📋 View Tasks",
        "✅ Update Task Status",
        "🗑️ Delete Completed Tasks"
    ])

    # Add Task
    with tab1:
        containers = requests.get(f"{API_URL}/inventory").json()
        container_dict = {f"container #{c['container_id']}": c['container_id'] for c in containers}
        selected_container = st.selectbox("Select Container", list(container_dict.keys()))
        action = st.selectbox("Action", ["Pick", "Drop", "Move", "Check Stock"])
        if st.button("Add Task"):
            requests.post(f"{API_URL}/tasks", json={
                "container_id": container_dict[selected_container],
                "action": action
            })
            st.success(f"Task added for {selected_container}")
            st.success("✔ Operation Completed Successfully")
            st.warning("⚠ Please check the input")


    # View Tasks
    with tab2:
        df_tasks = pd.DataFrame(requests.get(f"{API_URL}/tasks").json())
        st.dataframe(df_tasks)

    # Update Task Status
    with tab3:
        df_tasks = pd.DataFrame(requests.get(f"{API_URL}/tasks").json())
        task_ids = df_tasks['task_id'].tolist()
        selected_task = st.selectbox("Select Task ID", task_ids)
        new_status = st.selectbox("Update Status", ["pending", "in_progress", "completed"])
        if st.button("Update Task Status"):
            requests.put(f"{API_URL}/tasks/update", json={
                "task_id": selected_task,
                "status": new_status,
                "started_at": None,
                "completed_at": None
            })
            st.success(f"Task {selected_task} status updated")
            st.success("✔ Operation Completed Successfully")
            st.warning("⚠ Please check the input")


    # Delete Completed Tasks
    with tab4:
        if st.button("Delete All Completed Tasks"):
            requests.delete(f"{API_URL}/tasks/delete_completed")
            st.warning("All completed tasks deleted")

# Scheduler 
elif menu == "⚙️ Scheduler":
    st.title("⚙️ Run Scheduler")
    if st.button("Run FIFO Scheduler"):
        requests.post(f"{API_URL}/scheduler/run")
        st.success("Scheduler executed successfully")
        st.success("✔ Operation Completed Successfully")
        st.warning("⚠ Please check the input")

# Robots 
elif menu == "🚀 Robots":
    st.title("🚀 Robot Simulation")
    if st.button("Simulate Robot Movement / Battery"):
        requests.post(f"{API_URL}/robots/simulate")
        st.success("Robots simulated successfully")
        st.success("✔ Operation Completed Successfully")
        st.warning("⚠ Please check the input")

