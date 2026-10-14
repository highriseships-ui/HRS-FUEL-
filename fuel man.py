import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import altair as alt
from datetime import datetime
import json
import os
import io
import hashlib

# --- CONFIG & VERSIONING ---
APP_VERSION = "v1.3.1"
st.set_page_config(page_title="HRS Fleet Manager", layout="wide", page_icon="⚓")

# --- PERSISTENT STORAGE FILES ---
PINS_FILE = "hrs_pins.json"
LEDGER_FILE = "hrs_ledger_db.csv"
HASHES_FILE = "hrs_uploaded_hashes.json"
MASTER_RECOVERY_CODE = "181112"

def load_pins():
    if os.path.exists(PINS_FILE):
        try:
            with open(PINS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"owner_pin": "131509", "assistant_pin": "3576"}

def save_pins(pins_dict):
    with open(PINS_FILE, "w") as f:
        json.dump(pins_dict, f)

def load_hashes():
    if os.path.exists(HASHES_FILE):
        try:
            with open(HASHES_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_hashes(hashes_set):
    with open(HASHES_FILE, "w") as f:
        json.dump(list(hashes_set), f)

if "pins" not in st.session_state:
    st.session_state.pins = load_pins()

if "processed_hashes" not in st.session_state:
    st.session_state.processed_hashes = load_hashes()

# --- TWO-TIER AUTHENTICATION GATE & RECOVERY ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.recovered_login = False

if not st.session_state.authenticated:
    st.title("⚓ HRS Fleet Fuel Manager")
    st.subheader("🔐 Secure Portal Access")
    st.markdown("Please enter your PIN to continue.")
    
    with st.form("login_form"):
        pin_input = st.text_input("Enter PIN:", type="password", max_chars=6, placeholder="PIN")
        submit_login = st.form_submit_button("🔓 Login to Fleet Manager")
        
        if submit_login:
            if pin_input == st.session_state.pins["owner_pin"]:
                st.session_state.authenticated = True
                st.session_state.user_role = "Owner"
                st.session_state.recovered_login = False
                st.rerun()
            elif pin_input == st.session_state.pins["assistant_pin"]:
                st.session_state.authenticated = True
                st.session_state.user_role = "Assistant"
                st.session_state.recovered_login = False
                st.rerun()
            else:
                st.error("🚨 Invalid PIN. Please try again.")
            
    st.markdown("---")
    with st.expander("❓ Forgot Owner PIN?"):
        st.markdown("Enter your **Master Recovery Code** to unlock your Owner profile and reset your PIN.")
        with st.form("recovery_form"):
            rec_in = st.text_input("Master Recovery Code:", type="password", max_chars=6, key="rec")
            if st.form_submit_button("🛠️ Unlock Owner Profile"):
                if rec_in == MASTER_RECOVERY_CODE:
                    st.session_state.authenticated = True
                    st.session_state.user_role = "Owner"
                    st.session_state.recovered_login = True
                    st.rerun()
                else:
                    st.error("🚨 Invalid Master Recovery Code.")
    st.stop()

# --- TOP BAR: USER ROLE, LOGOUT & LIVE CLOCK ---
top_col1, top_col2, top_col3 = st.columns([6, 2, 2])
with top_col1:
    st.title("⚓ HRS Fleet Fuel Manager")
with top_col2:
    role_label = st.session_state.user_role
    st.markdown(
        f"<div style='text-align:right;padding-top:15px;'>👤 Logged in as: <b>{role_label}</b></div>",
        unsafe_allow_html=True
    )
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_role = None
        st.session_state.recovered_login = False
        st.rerun()
with top_col3:
    components.html(
        f"""
        <div style="font-family:sans-serif;text-align:right;color:gray;padding-top:10px;">
            <div id="clock" style="font-size:15px;font-weight:bold;"></div>
            <div style="font-size:13px;margin-top:2px;">Version: {APP_VERSION}</div>
        </div>
        <script>
            function updateClock() {{
                var now = new Date();
                var opt = {{
                    day:'2-digit', month:'2-digit', year:'numeric',
                    hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true
                }};
                document.getElementById('clock').innerHTML = "Live: " + now.toLocaleString('en-IN', opt);
                setTimeout(updateClock, 1000);
            }}
            updateClock();
        </script>
        """,
        height=55
    )

if st.session_state.get("recovered_login", False):
    st.warning("🔓 Logged in via Master Recovery Code (181112). Go to the bottom of Tab 3 ('⚙️ Master Ledger & Audit') to update your Owner PIN.")

# --- 1. INITIALIZE DATABASE & BALANCES ---
vessels = ["Falcon High", "Aarya", "Kingfisher", "Phoenix"]
equipments = [
    "Main Engine", "D.G. Engine", "Deck Honda Pump", 
    "Auxiliary Engine", "Anchor Engine", "Stove Fuel Consumption", "Others"
]

LEDGER_COLUMNS = [
    "Record ID", "Timestamp", "Date", "Vessel", "Voyage No", "Voyage Month",
    "Voyage Desc", "Type", "Start Time", "Stop Time", "Duration (Hrs)",
    "Distance (NM)", "Liters", "Counterparty", "Equipment", "Remarks",
    "Logged By", "Status", "Original_ID"
]

def load_ledger():
    if os.path.exists(LEDGER_FILE):
        try:
            df = pd.read_csv(LEDGER_FILE)
            num_cols = ["Liters", "Distance (NM)", "Duration (Hrs)"]
            for col in LEDGER_COLUMNS:
                if col not in df.columns:
                    df[col] = 0.0 if col in num_cols else "-"
            return df[LEDGER_COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=LEDGER_COLUMNS)

def save_ledger():
    st.session_state.ledger.to_csv(LEDGER_FILE, index=False)

def add_ledger_entry(date_s, ves, voy_no, v_mon, voy_desc, r_type, st_t, sp_t, dur, dist, ltrs, cp, eq, rem, orig="-"):
    ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    row_data = {
        "Record ID": st.session_state.next_id,
        "Timestamp": ts,
        "Date": date_s,
        "Vessel": ves,
        "Voyage No": voy_no,
        "Voyage Month": v_mon,
        "Voyage Desc": voy_desc,
        "Type": r_type,
        "Start Time": st_t,
        "Stop Time": sp_t,
        "Duration (Hrs)": dur,
        "Distance (NM)": dist,
        "Liters": ltrs,
        "Counterparty": cp,
        "Equipment": eq,
        "Remarks": rem,
        "Logged By": st.session_state.user_role,
        "Status": "Active",
        "Original_ID": orig
    }
    new_df = pd.DataFrame([row_data])
    st.session_state.ledger = pd.concat([st.session_state.ledger, new_df], ignore_index=True)
    st.session_state.next_id += 1
    save_ledger()
    return ts

if "start_balances" not in st.session_state:
    st.session_state.start_balances = {
        "Falcon High": 4250.0, "Aarya": 1000.0, "Kingfisher": 1500.0, "Phoenix": 4150.0
    }

if "ledger" not in st.session_state:
    st.session_state.ledger = load_ledger()
    if st.session_state.ledger.empty:
        st.session_state.next_id = 1
    else:
        max_id = pd.to_numeric(st.session_state.ledger["Record ID"], errors="coerce").max()
        st.session_state.next_id = int(max_id) + 1 if pd.notna(max_id) else 1

if "session_logs" not in st.session_state:
    st.session_state.session_logs = []

# --- 2. DYNAMIC CALCULATORS ---
def get_active_ledger():
    if st.session_state.ledger.empty:
        return st.session_state.ledger
    return st.session_state.ledger[st.session_state.ledger["Status"] == "Active"]

def sum_liters(df_sub):
    return pd.to_numeric(df_sub["Liters"], errors="coerce").fillna(0).sum()

def get_current_balance(vessel_name):
    bal = st.session_state.start_balances[vessel_name]
    df = get_active_ledger()
    if len(df) > 0:
        cons = sum_liters(df
