import streamlit as st
import requests
import pandas as pd


# Configuration
BACKEND_URL = "http://localhost:5000"

CONTAINER_OPTIONS = [1001, 1002, 1003, 1004, 1005]
RACK_OPTIONS = ["RACK_A", "RACK_B", "RACK_C", "RACK_D"]

st.set_page_config(
    page_title="Warehouse Robot Dashboard",
    layout="wide"
)


# Styling
st.markdown("""
<style>
.health-card {
    background: linear-gradient(135deg, #1e293b, #334155);
    padding: 22px;
    border-radius: 18px;
    text-align: center;
    color: white;
    box-shadow: 0 10px 24px rgba(0,0,0,0.3);
}
.health-title {
    font-size: 17px;
    opacity: 0.85;
}
.health-value {
    font-size: 28px;
    font-weight: 700;
    margin-top: 8px;
}
</style>
""", unsafe_allow_html=True)

st.title(" Warehouse Robot Control Panel")
st.caption("Monitoring & task management dashboard ")


# Backend helpers
def safe_get(endpoint):
    try:
        r = requests.get(f"{BACKEND_URL}{endpoint}", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Backend error on {endpoint}: {e}")
        return None

def safe_post(endpoint, payload):
    try:
        r = requests.post(
            f"{BACKEND_URL}{endpoint}",
            json=payload,
            timeout=3
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"POST error: {e}")
        return None

# Tabs
tabs = st.tabs([
    " System Health",
    " Robots",
    " Tasks",
    " Logs"
])


# Health Tab

with tabs[0]:
    st.subheader("System Status")

    health = safe_get("/health")
    if health:
        c1, c2, c3 = st.columns(3)

        c1.markdown("""
        <div class="health-card">
            <div class="health-title">Backend</div>
            <div class="health-value">ONLINE</div>
        </div>
        """, unsafe_allow_html=True)

        c2.markdown(f"""
        <div class="health-card">
            <div class="health-title">MQTT Broker</div>
            <div class="health-value">
                {"CONNECTED" if health["mqtt_connected"] else "DISCONNECTED"}
            </div>
        </div>
        """, unsafe_allow_html=True)

        c3.markdown(f"""
        <div class="health-card">
            <div class="health-title">Server Time</div>
            <div class="health-value">
                {health["time"].split("T")[1][:8]}
            </div>
        </div>
        """, unsafe_allow_html=True)


# Robots Tab
with tabs[1]:
    st.subheader("Robots Monitor")

    robots = safe_get("/robots")
    if robots:
        df = pd.DataFrame(robots)

        if not df.empty:
            st.dataframe(
                df[[
                    "robot_id",
                    "name",
                    "status",
                    "fsm_state",
                    "battery",
                    "last_seen"
                ]],
                use_container_width=True
            )
        else:
            st.info("No robots registered yet")


# Tasks Tab
with tabs[2]:
    st.subheader("Create Warehouse Task")

    with st.form("create_task_form"):
        container_id = st.selectbox(
            "Container ID",
            CONTAINER_OPTIONS
        )

        action = st.selectbox(
            "Action",
            ["PICK", "DROP"]
        )

        source_rack = st.selectbox(
            "Source Rack",
            RACK_OPTIONS
        )

        destination_rack = st.selectbox(
            "Destination Rack",
            RACK_OPTIONS
        )

        submit = st.form_submit_button(" Create Task")

        if submit:
            if source_rack == destination_rack:
                st.warning(
                    "Source rack and destination rack must be different."
                )
            else:
                payload = {
                    "container_id": container_id,
                    "action": action,
                    "source_rack": source_rack,
                    "destination_rack": destination_rack
                }

                result = safe_post("/tasks/create", payload)

                if result:
                    task = result["task"]

                    st.success("Task created successfully")

                    

    st.divider()
    st.subheader("All Tasks")

    tasks = safe_get("/tasks")
    if tasks:
        df = pd.DataFrame(tasks)
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No tasks available")


# Logs Tab
with tabs[3]:
    st.subheader("Robot Event Logs")

    logs = safe_get("/logs")
    if logs:
        df = pd.DataFrame(logs)

        if not df.empty:
            st.dataframe(
                df[[
                    "timestamp",
                    "robot_id",
                    "task_id",
                    "event",
                    "details"
                ]],
                use_container_width=True
            )
        else:
            st.info("No logs recorded yet")