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
APP_VERSION = "v1.3.4"
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

# Initialize session state for the post-upload tally
if "last_upload_filename" not in st.session_state:
    st.session_state.last_upload_filename = None
    st.session_state.last_upload_total = 0.0
    st.session_state.last_upload_summary_df = pd.DataFrame()

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
        f'''
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
        ''',
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
        cons = sum_liters(df[(df["Vessel"] == vessel_name) & (df["Type"] == "Consumption")])
        t_out = sum_liters(df[(df["Vessel"] == vessel_name) & (df["Type"] == "Transfer Out")])
        s_in = sum_liters(df[(df["Vessel"] == vessel_name) & (df["Type"] == "Supply Received")])
        t_in = sum_liters(df[(df["Counterparty"] == vessel_name) & (df["Type"] == "Transfer Out")])
        bal = bal - cons - t_out + s_in + t_in
    return bal

def get_consumption_breakdown(vessel_name):
    df = get_active_ledger()
    c_df = df[(df["Vessel"] == vessel_name) & (df["Type"] == "Consumption")]
    me = sum_liters(c_df[c_df["Equipment"] == "Main Engine"])
    dg = sum_liters(c_df[c_df["Equipment"] == "D.G. Engine"])
    pump = sum_liters(c_df[c_df["Equipment"] == "Deck Honda Pump"])
    aux = sum_liters(c_df[c_df["Equipment"] == "Auxiliary Engine"])
    anc = sum_liters(c_df[c_df["Equipment"] == "Anchor Engine"])
    stv = sum_liters(c_df[c_df["Equipment"] == "Stove Fuel Consumption"])
    oth = sum_liters(c_df[c_df["Equipment"].astype(str).str.startswith("Others", na=False)])
    return me, dg, pump, aux, anc, stv, oth

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Fleet Dashboard", "📝 Crew Log Entry", "⚙️ Master Ledger & Audit"])

# ==========================================
# TAB 1: FLEET DASHBOARD 
# ==========================================
with tab1:
    st.subheader("🚢 Fleet Overview")
    overview_cols = st.columns(4)
    for i, v in enumerate(vessels):
        bal = get_current_balance(v)
        with overview_cols[i]:
            st.write(f"**{v}**")
            if bal < 1000:
                st.markdown(f"<h3 style='color:#ff4b4b;margin-top:-15px;'>{bal:.1f} L ⚠️</h3>", unsafe_allow_html=True)
            else:
                st.markdown(f"<h3 style='margin-top:-15px;'>{bal:.1f} L</h3>", unsafe_allow_html=True)
                
    st.divider()
    st.subheader("Live Inventory & Consumption Analytics")
    
    for v in vessels:
        bal = get_current_balance(v)
        me, dg, pump, aux, anc, stv, oth = get_consumption_breakdown(v)
        
        with st.container():
            st.markdown(f"### 🚢 {v}")
            col_metrics, col_chart = st.columns([1, 2])
            
            with col_metrics:
                st.caption("Live Tank Balance")
                if bal < 1000:
                    st.markdown(f"<h2 style='color:#ff4b4b;margin-top:-15px;'>{bal:.1f} L ⚠️</h2>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<h2 style='margin-top:-15px;color:#2e8b57;'>{bal:.1f} L 🟢</h2>", unsafe_allow_html=True)
                
                st.write("**Quick Breakdown:**")
                st.write(f"⚙️ Main: **{me} L** | ⚡ D.G.: **{dg} L** | 🌊 Pump: **{pump} L**")
                st.write(f"🔋 Aux: **{aux} L** | ⚓ Anchor: **{anc} L**")
                st.write(f"🍳 Stove: **{stv} L** | 🔧 Others: **{oth} L**")

            with col_chart:
                chart_data = pd.DataFrame({
                    "Equipment": ["Main", "D.G.", "Pump", "Aux", "Anchor", "Stove", "Others"],
                    "Liters": [me, dg, pump, aux, anc, stv, oth]
                })
                chart = alt.Chart(chart_data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                    x=alt.X('Equipment', axis=alt.Axis(labelAngle=0, title=None)),
                    y=alt.Y('Liters', axis=alt.Axis(title="Liters Consumed")),
                    color=alt.value("#3b82f6") 
                ).properties(height=200)
                st.altair_chart(chart, use_container_width=True)
            st.markdown("---")

# ==========================================
# TAB 2: CREW LOG OPERATIONS & BULK UPLOAD
# ==========================================
with tab2:
    st.subheader("Add New Record")
    
    c1, c2 = st.columns(2)
    vessel = c1.selectbox("🚢 Select Your Vessel", vessels)
    action_type = c2.radio("⛽ What are you logging?", ["🔥 Fuel Consumed", "📥 Received Supply", "📤 Transferred Out"])
    
    st.markdown("---")
    st.write("🗺️ **Voyage Details (Berth-to-Berth)**")
    v_col1, v_col2 = st.columns([1, 3])
    voyage_no = v_col1.text_input("Voyage Number", placeholder="e.g. 1")
    voyage_desc = v_col2.text_input("Voyage Description", placeholder="e.g. Berth 1 to Anchorage")
    
    st.markdown("---")
    
    if action_type == "🔥 Fuel Consumed":
        with st.form("cons_form"):
            st.write("⏱️ **Operation Timing**")
            t_col1, t_col2 = st.columns(2)
            with t_col1:
                start_date = st.date_input("Start Date", format="DD/MM/YYYY", key="sd_cons")
                start_time = st.time_input("Start Time", key="st_cons")
            with t_col2:
                stop_date = st.date_input("Stop Date", format="DD/MM/YYYY", key="ed_cons")
                stop_time = st.time_input("Stop Time", key="et_cons")

            st.write("⚙️ **Equipment & Fuel**")
            e_col1, e_col2, e_col3 = st.columns(3)
            
            equip = e_col1.selectbox("Which Equipment?", equipments)
            other_desc = ""
            if equip == "Others":
                other_desc = e_col1.text_input("Please Specify 'Others'", placeholder="e.g., Crane")
                
            distance_nm = e_col2.number_input("🗺️ Distance Run (NM)", min_value=0.0, step=0.1)
            liters = e_col3.number_input("💧 Total Liters Used", min_value=0.0, step=1.0)
            remarks = st.text_input("📝 Remarks (Optional)")
            
            if st.form_submit_button("✅ Save Fuel Log"):
                dt_start = datetime.combine(start_date, start_time)
                dt_stop = datetime.combine(stop_date, stop_time)
                
                if dt_stop <= dt_start:
                    st.error("🚨 Error: Stop Date & Time must be after Start Date & Time.")
                elif not voyage_no:
                    st.error("🚨 Error: Voyage Number is required.")
                elif equip == "Others" and not other_desc:
                    st.error("🚨 Error: Please specify the 'Others' equipment name.")
                else:
                    dur_hrs = round((dt_stop - dt_start).total_seconds() / 3600, 2)
                    v_mon = start_date.strftime("%b-%Y")
                    f_eq = f"Others ({other_desc})" if equip == "Others" else equip
                    
                    ts = add_ledger_entry(
                        start_date.strftime("%d-%m-%Y"), vessel, voyage_no, v_mon, voyage_desc,
                        "Consumption", dt_start.strftime("%d-%m-%Y %H:%M"),
                        dt_stop.strftime("%d-%m-%Y %H:%M"), dur_hrs, distance_nm,
                        liters, "-", f_eq, remarks
                    )
                    role = st.session_state.user_role
                    msg = f"✅ [{role}] Logged {liters}L for {f_eq} ({dur_hrs} Hrs | {distance_nm} NM)."
                    st.session_state.session_logs.insert(0, f"{ts} | {msg}")
                    st.success(msg)

    elif action_type == "📥 Received Supply":
        with st.form("supply_form"):
            log_date = st.date_input("Date Received", format="DD/MM/YYYY", key="d_sup")
            c_col1, c_col2 = st.columns(2)
            source = c_col1.selectbox("🚚 Received From", ["Terminal"])
            liters = c_col2.number_input("💧 Liters Received", min_value=0.0, step=1.0)
            remarks = st.text_input("📝 Remarks (Optional)")
            
            if st.form_submit_button("✅ Save Supply Received"):
                if not voyage_no:
                    st.error("🚨 Error: Voyage Number is required.")
                else:
                    v_mon = log_date.strftime("%b-%Y")
                    ts = add_ledger_entry(
                        log_date.strftime("%d-%m-%Y"), vessel, voyage_no, v_mon, voyage_desc,
                        "Supply Received", "-", "-", 0.0, 0.0, liters, source, "-", remarks
                    )
                    msg = f"✅ [{st.session_state.user_role}] Received {liters}L from {source}."
                    st.session_state.session_logs.insert(0, f"{ts} | {msg}")
                    st.success(msg)

    elif action_type == "📤 Transferred Out":
        with st.form("transfer_form"):
            log_date = st.date_input("Date Transferred", format="DD/MM/YYYY", key="d_tran")
            c_col1, c_col2 = st.columns(2)
            other_vessels = [v for v in vessels if v != vessel]
            destination = c_col1.selectbox("🚢 Transferred To (Barge)", other_vessels)
            liters = c_col2.number_input("💧 Liters Transferred", min_value=0.0, step=1.0)
            remarks = st.text_input("📝 Remarks (Optional)")
            
            if st.form_submit_button("✅ Save Transfer Out"):
                if not voyage_no:
                    st.error("🚨 Error: Voyage Number is required.")
                else:
                    v_mon = log_date.strftime("%b-%Y")
                    ts = add_ledger_entry(
                        log_date.strftime("%d-%m-%Y"), vessel, voyage_no, v_mon, voyage_desc,
                        "Transfer Out", "-", "-", 0.0, 0.0, liters, destination, "-", remarks
                    )
                    msg = f"✅ [{st.session_state.user_role}] Transferred {liters}L to {destination}."
                    st.session_state.session_logs.insert(0, f"{ts} | {msg}")
                    st.success(msg)

    if st.session_state.session_logs:
        st.markdown("---")
        st.markdown("### 📋 Recent Activity (This Session)")
        for log in st.session_state.session_logs[:3]:
            st.text(log)

    st.markdown("---")
    st.subheader("📂 Offline Logs: Bulk CSV Upload (Two-Tier Smart Safeguard)")

    # --- IMMEDIATE POST-UPLOAD SUMMARY ---
    if st.session_state.last_upload_filename:
        st.success(f"✅ Data Injected Successfully from: **{st.session_state.last_upload_filename}**")
        st.markdown("#### 📋 File Tally (Cross-check this with your paper notes)")
        st.info(f"**Total Consumption Logged:** `{st.session_state.last_upload_total:.1f} L`")
        if not st.session_state.last_upload_summary_df.empty:
            st.dataframe(st.session_state.last_upload_summary_df, use_container_width=True, hide_index=True)
        if st.button("Dismiss Tally"):
            st.session_state.last_upload_filename = None
            st.rerun()
        st.markdown("---")

    st.info("Upload converted CSV files below. Identical files (even if renamed) are strictly blocked, while separate voyages with similar readings will prompt for your confirmation.")
    uploaded_csv = st.file_uploader("📂 Drag and drop your CSV file here, or tap to browse", type=["csv"])
    
    if uploaded_csv:
        file_bytes = uploaded_csv.getvalue()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        
        force_upload = False
        # TIER 1: Exact File Content Match (Hard Block + Override)
        if file_hash in st.session_state.processed_hashes:
            st.error("🚨 **Duplicate File Blocked:** This exact CSV file content has already been uploaded to the system. Even if saved under a different name, re-uploading the same file is restricted.")
            force_upload = st.checkbox("☑️ I acknowledge this file was previously uploaded, but I want to force re-upload it (e.g., deleted test entries).", key="force_reupload")
            
        if file_hash not in st.session_state.processed_hashes or force_upload:
            try:
                df_upload = pd.read_csv(io.BytesIO(file_bytes))
                
                # --- SMART AUTO-MAPPER FOR VESSEL NAMES ---
                if "Vessel" in df_upload.columns:
                    def clean_vessel_name(raw_name):
                        v_str = str(raw_name).lower()
                        if "falcon" in v_str: return "Falcon High"
                        if "aarya" in v_str or "arya" in v_str: return "Aarya"
                        if "kingfisher" in v_str: return "Kingfisher"
                        if "phoenix" in v_str: return "Phoenix"
                        return str(raw_name).strip()
                    
                    df_upload["Vessel"] = df_upload["Vessel"].apply(clean_vessel_name)
                # ------------------------------------------

                # TIER 2: Smart Similarity Check
                active_check_df = get_active_ledger()
                similar_warnings = []
                
                if not active_check_df.empty and all(c in df_upload.columns for c in ["Vessel", "Equipment", "Liters"]):
                    for idx, u_row in df_upload.iterrows():
                        u_ves = str(u_row.get("Vessel", ""))
                        u_eq = str(u_row.get("Equipment", ""))
                        u_ltr = pd.to_numeric(u_row.get("Liters", 0), errors="coerce") or 0.0
                        u_dt = str(u_row.get("Date", ""))
                        
                        matches = active_check_df[
                            (active_check_df["Vessel"].astype(str) == u_ves) &
                            (active_check_df["Equipment"].astype(str) == u_eq) &
                            (pd.to_numeric(active_check_df["Liters"], errors="coerce") == u_ltr)
                        ]
                        if not matches.empty:
                            existing_voy = matches.iloc[0]["Voyage No"]
                            existing_dt = matches.iloc[0]["Date"]
                            similar_warnings.append(
                                f"Row {idx+1} ({u_ves} | {u_eq} | {u_ltr} L on {u_dt}) matches existing reading from Voyage {existing_voy} ({existing_dt})."
                            )
                
                allow_inject = True
                if similar_warnings:
                    st.warning(
                        f"⚠️ **Similar Data / Readings Detected ({len(similar_warnings)} matching entries):**\n"
                        "This file contains fuel readings that match existing records in your ledger:"
                    )
                    with st.expander("View Matching Readings Details"):
                        for w in similar_warnings[:10]:
                            st.write(f"- {w}")
                        if len(similar_warnings) > 10:
                            st.write(f"...and {len(similar_warnings) - 10} more matching readings.")
                            
                    allow_inject = st.checkbox(
                        "☑️ Do you really want to upload this? I confirm these are legitimate readings for a separate trip/log.",
                        key=f"confirm_sim_{file_hash[:8]}"
                    )
                
                if st.button("Inject Data into Master Ledger", disabled=not allow_inject):
                    for _, row in df_upload.iterrows():
                        r_dict = row.to_dict()
                        r_dict["Record ID"] = st.session_state.next_id
                        r_dict["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        r_dict["Logged By"] = st.session_state.user_role
                        r_dict["Status"] = "Active"
                        r_dict["Original_ID"] = "-"
                        
                        if "Distance (NM)" not in r_dict:
                            r_dict["Distance (NM)"] = 0.0
                        if "Voyage Month" not in r_dict:
                            try:
                                dt_o = datetime.strptime(str(r_dict["Date"]), "%d-%m-%Y")
                                r_dict["Voyage Month"] = dt_o.strftime("%b-%Y")
                            except Exception:
                                r_dict["Voyage Month"] = "Unknown"
                                
                        c_row = {col: r_dict.get(col, "-") for col in LEDGER_COLUMNS}
                        st.session_state.ledger = pd.concat(
                            [st.session_state.ledger, pd.DataFrame([c_row])],
                            ignore_index=True
                        )
                        st.session_state.next_id += 1
                    
                    save_ledger()
                    st.session_state.processed_hashes.add(file_hash)
                    save_hashes(st.session_state.processed_hashes)
                    
                    # Compute Post-Upload Tally Before Rerun
                    st.session_state.last_upload_filename = uploaded_csv.name
                    df_tally = df_upload.copy()
                    if "Type" not in df_tally.columns:
                        df_tally["Type"] = "Consumption"
                    if "Voyage No" not in df_tally.columns:
                        df_tally["Voyage No"] = "Unknown"
                        
                    cons_tally = df_tally[df_tally["Type"].astype(str).str.contains("Consumption", case=False, na=False)].copy()
                    cons_tally["Liters"] = pd.to_numeric(cons_tally.get("Liters", 0), errors="coerce").fillna(0.0)
                    
                    st.session_state.last_upload_total = cons_tally["Liters"].sum()
                    if not cons_tally.empty:
                        st.session_state.last_upload_summary_df = cons_tally.groupby(["Vessel", "Voyage No", "Equipment"])["Liters"].sum().reset_index()
                    else:
                        st.session_state.last_upload_summary_df = pd.DataFrame()

                    st.rerun()
            except Exception as e:
                st.error(f"Error reading CSV format: {e}")

# ==========================================
# TAB 3: MASTER LEDGER, AUDIT & VOYAGE ANALYTICS
# ==========================================
with tab3:
    st.subheader("🔍 Search, Filter & Manage Master Ledger")
    
    f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
    vessel_filter = f_col1.selectbox("Filter by Vessel", ["All Fleet"] + vessels)
    role_filter = f_col2.selectbox("Filter by Role (Logged By)", ["All Roles", "Owner", "Assistant"])
    search_query = f_col3.text_input("Search Keyword (Voyage, Remarks, Equipment, Date, etc.)")
    
    active_df = get_active_ledger().copy()
    if not active_df.empty:
        active_df.insert(0, 'S.No', range(1, 1 + len(active_df)))
    
    display_df = active_df.copy()
    if vessel_filter != "All Fleet":
        display_df = display_df[display_df["Vessel"] == vessel_filter]
    if role_filter != "All Roles":
        display_df = display_df[display_df["Logged By"] == role_filter]
    if search_query:
        mask = display_df.astype(str).apply(
            lambda x: x.str.contains(search_query, case=False)
        ).any(axis=1)
        display_df = display_df[mask]
        
    # --- INTERACTIVE CHECKBOX LEDGER & PAGINATION ---
    if not display_df.empty:
        st.markdown("#### ☑️ Interactive Ledger")
        st.caption("Tick individual checkboxes or use 'Select All' on the current page to bulk-delete entries.")
        
        # Pagination Logic
        if "current_page" not in st.session_state:
            st.session_state.current_page = 1
            
        total_rows = len(display_df)
        
        pag_col1, pag_col2, pag_col3, pag_col4 = st.columns([2, 1, 1, 2])
        with pag_col1:
            page_size_sel = st.selectbox("Rows per page:", [10, 25, 50, "All"], index=0)
            
        page_size = total_rows if page_size_sel == "All" else int(page_size_sel)
        total_pages = max(1, (total_rows - 1) // page_size + 1)
        
        if st.session_state.current_page > total_pages:
            st.session_state.current_page = total_pages
        elif st.session_state.current_page < 1:
            st.session_state.current_page = 1
            
        with pag_col2:
            st.write("") 
            st.write("")
            if st.button("⬅️ Prev", use_container_width=True, disabled=(st.session_state.current_page <= 1)):
                st.session_state.current_page -= 1
                st.rerun()
        with pag_col3:
            st.write("")
            st.write("")
            if st.button("Next ➡️", use_container_width=True, disabled=(st.session_state.current_page >= total_pages)):
                st.session_state.current_page += 1
                st.rerun()
        with pag_col4:
            st.write("")
            st.write("")
            st.markdown(f"**Page {st.session_state.current_page} of {total_pages}** (Total: {total_rows})")

        # Slice the dataframe for the current page
        start_idx = (st.session_state.current_page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_df = display_df.iloc[start_idx:end_idx].copy()
        
        sel_col1, sel_col2 = st.columns([1, 3])
        select_all = sel_col1.checkbox("☑️ Select All on Current Page", value=False, key="select_all_toggle")
        
        paginated_df.insert(0, "Select", select_all)
        disabled_cols = [c for c in paginated_df.columns if c != "Select"]
        
        edited_multidel = st.data_editor(
            paginated_df,
            use_container_width=True,
            hide_index=True,
            disabled=disabled_cols,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", help="Check to select this entry for deletion", default=False)
            },
            key=f"multi_delete_editor_p{st.session_state.current_page}"
        )
        
        selected_rows = edited_multidel[edited_multidel["Select"] == True]
        selected_sno = selected_rows["S.No"].tolist()
        
        if selected_sno:
            st.warning(f"⚠️ You have checked **{len(selected_sno)}** entry/entries for deletion on this page.")
            del_col1, del_col2 = st.columns([3, 1])
            del_reason = del_col1.text_input("Reason for Deletion (Required for Audit History)", placeholder="e.g., Duplicate entry / Wrong voyage log", key="bulk_del_reason")
            
            with del_col2:
                st.write("")
                st.write("")
                if st.button("🗑️ Delete Checked Entries", type="primary", use_container_width=True):
                    if not del_reason:
                        st.error("🚨 Please enter a reason for the audit log before deleting.")
                    else:
                        role = st.session_state.user_role
                        for sno in selected_sno:
                            t_row = display_df[display_df["S.No"] == sno].iloc[0]
                            r_id = t_row["Record ID"]
                            idx_mask = st.session_state.ledger["Record ID"] == r_id
                            old_rem = str(t_row['Remarks'])
                            st.session_state.ledger.loc[idx_mask, "Status"] = f"Voided (by {role})"
                            st.session_state.ledger.loc[idx_mask, "Remarks"] = f"{old_rem} | Bulk Deleted by {role}: {del_reason}"
                        
                        save_ledger()
                        st.success(f"✅ Successfully deleted {len(selected_sno)} entries (Recorded under {role}).")
                        st.rerun()
                        
        st.download_button(
            label="📥 Export Full Filtered Ledger to CSV",
            data=display_df.to_csv(index=False).encode('utf-8'),
            file_name=f"HRS_Fuel_Ledger_{datetime.now().strftime('%d_%m_%Y')}.csv",
            mime="text/csv",
        )
        
        st.markdown("---")
        st.subheader("✏️ Edit / Correct a Single Entry")
        sno_to_amend = st.selectbox("Select S.No to Edit Values", display_df["S.No"].tolist())
        target_row = display_df[display_df["S.No"] == sno_to_amend].iloc[0]
        rec_id = target_row["Record ID"]
        
        st.write(
            f"**Editing S.No {sno_to_amend}:** {target_row['Vessel']} | "
            f"{target_row['Type']} | {target_row['Liters']}L | "
            f"Originally Logged By: **{target_row['Logged By']}**"
        )
        amend_opts = ["Correct Error (Adjust Liters / Distance)", "Void/Delete This Entry"]
        amend_action = st.radio("Action Type", amend_opts, horizontal=True)
        
        with st.form("amend_form"):
            new_liters = 0.0
            new_distance = 0.0
            if amend_action == "Correct Error (Adjust Liters / Distance)":
                a_col1, a_col2 = st.columns(2)
                cur_l = float(pd.to_numeric(target_row['Liters'], errors='coerce') or 0.0)
                cur_d = float(pd.to_numeric(target_row['Distance (NM)'], errors='coerce') or 0.0)
                new_liters = a_col1.number_input("Corrected Liters", min_value=0.0, step=1.0, value=cur_l)
                new_distance = a_col2.number_input("Corrected Distance (NM)", min_value=0.0, step=0.1, value=cur_d)
            
            amend_reason = st.text_input("Reason for Amendment (Required)")
            
            if st.form_submit_button("💾 Apply Amendment"):
                if not amend_reason:
                    st.error("You must provide a reason for the audit log.")
                else:
                    ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    role = st.session_state.user_role
                    idx_mask = st.session_state.ledger["Record ID"] == rec_id
                    st.session_state.ledger.loc[idx_mask, "Status"] = f"Voided (by {role})"
                    
                    if amend_action == "Correct Error (Adjust Liters / Distance)":
                        c_row = target_row.drop('S.No').to_dict()
                        c_row["Record ID"] = st.session_state.next_id
                        c_row["Timestamp"] = ts
                        c_row["Liters"] = new_liters
                        c_row["Distance (NM)"] = new_distance
                        c_row["Remarks"] = f"Correction by {role}. Reason: {amend_reason}"
                        c_row["Logged By"] = role
                        c_row["Status"] = "Active"
                        c_row["Original_ID"] = rec_id
                        
                        st.session_state.ledger = pd.concat(
                            [st.session_state.ledger, pd.DataFrame([c_row])],
                            ignore_index=True
                        )
                        st.session_state.next_id += 1
                        save_ledger()
                        st.success(f"S.No {sno_to_amend} corrected by {role}.")
                    else:
                        old_rem = target_row['Remarks']
                        new_rem = f"{old_rem} | Voided by {role}: {amend_reason}"
                        st.session_state.ledger.loc[idx_mask, "Remarks"] = new_rem
                        save_ledger()
                        st.success(f"S.No {sno_to_amend} voided by {role}.")
                    st.rerun()
    else:
        st.info("No active records match your filter.")
        
    st.markdown("---")
    
    # --- VOYAGE SUMMARIES AND COMPARISONS ---
    st.subheader("📈 Voyage Summaries & Comparisons")
    st.markdown("Verify individual voyages or compare actual fuel spent per equipment in tabular format.")
    
    cons_df = active_df[active_df["Type"] == "Consumption"].copy()
    
    if not cons_df.empty and cons_df["Voyage No"].nunique() > 0:
        cons_df["Liters"] = pd.to_numeric(cons_df["Liters"], errors="coerce").fillna(0.0)
        cons_df["Voyage ID"] = (
            cons_df["Voyage No"].astype(str) + " (" + cons_df["Voyage Month"].astype(str) + ")"
        )
        
        modes = ["Single Voyage Summary (Quick Check)", "Compare Voyages (Single Vessel)", "Compare Vessels (Single Voyage)"]
        analysis_mode = st.radio("Select Analysis Mode:", modes, horizontal=True)

        if analysis_mode == "Single Voyage Summary (Quick Check)":
            v_comp = st.selectbox("Select Vessel", vessels, key="comp_ves_single_q")
            v_df = cons_df[cons_df["Vessel"] == v_comp]
            
            u_voys = v_df["Voyage ID"].unique()
            if len(u_voys) > 0:
                voy_sel = st.selectbox("Select Voyage to Verify", u_voys, key="voy_sel_q")
                voy_df_q = v_df[v_df["Voyage ID"] == voy_sel]
                
                tot_liters = voy_df_q["Liters"].sum()
                st.markdown(f"### ⛽ Total Fuel Consumed: **{tot_liters:.1f} L**")
                
                b_df = voy_df_q.groupby("Equipment")["Liters"].sum().reset_index()
                st.dataframe(b_df, use_container_width=True, hide_index=True)
            else:
                st.info(f"No consumption data logged for {v_comp} yet.")

        elif analysis_mode == "Compare Voyages (Single Vessel)":
            v_comp = st.selectbox("Select Vessel", vessels, key="comp_ves_single")
            v_df = cons_df[cons_df["Vessel"] == v_comp]
            
            u_voys = v_df["Voyage ID"].unique()
            if len(u_voys) > 0:
                c_col1, c_col2 = st.columns(2)
                voy_a = c_col1.selectbox("Base Voyage", u_voys, key="voy_a")
                def_idx = 1 if len(u_voys) > 1 else 0
                voy_b = c_col2.selectbox("Voyage to Compare", u_voys, index=def_idx, key="voy_b")
                
                if voy_a and voy_b:
                    if voy_a == voy_b:
                        st.warning("⚠️ Please select two different voyages to compare.")
                    else:
                        col_a = f"{voy_a} (L)"
                        col_b = f"{voy_b} (L)"
                        df_a = v_df[v_df["Voyage ID"] == voy_a].groupby("Equipment")["Liters"].sum().reset_index().rename(columns={"Liters": col_a})
                        df_b = v_df[v_df["Voyage ID"] == voy_b].groupby("Equipment")["Liters"].sum().reset_index().rename(columns={"Liters": col_b})
                        
                        comp_table = pd.DataFrame({"Equipment": equipments})
                        comp_table = pd.merge(comp_table, df_a, on="Equipment", how="left").fillna(0)
                        comp_table = pd.merge(comp_table, df_b, on="Equipment", how="left").fillna(0)
                        
                        diff = comp_table[col_b] - comp_table[col_a]
                        comp_table["Difference (L)"] = diff.apply(lambda x: f"+{x:.1f}" if x > 0 else f"{x:.1f}")
                        
                        st.dataframe(comp_table, use_container_width=True, hide_index=True)
                        
                        tot_a = v_df[v_df["Voyage ID"] == voy_a]["Liters"].sum()
                        tot_b = v_df[v_df["Voyage ID"] == voy_b]["Liters"].sum()
                        st.info(f"**Total Consumption:** {voy_a} burned **{tot_a:.1f} L** vs {voy_b} burned **{tot_b:.1f} L**.")
            else:
                st.info(f"No consumption data logged for {v_comp} yet.")
                
        elif analysis_mode == "Compare Vessels (Single Voyage)":
            u_voys = cons_df["Voyage ID"].unique()
            if len(u_voys) > 0:
                voy_comp = st.selectbox("Select Voyage", u_voys, key="comp_voy_multi")
                voy_df = cons_df[cons_df["Voyage ID"] == voy_comp]
                
                c_col1, c_col2 = st.columns(2)
                ves_a = c_col1.selectbox("Base Vessel", vessels, key="ves_a")
                ves_b = c_col2.selectbox("Vessel to Compare", vessels, index=1, key="ves_b")
                
                if ves_a and ves_b:
                    if ves_a == ves_b:
                        st.warning("⚠️ Please select two different vessels to compare.")
                    else:
                        col_a = f"{ves_a} (L)"
                        col_b = f"{ves_b} (L)"
                        df_a = voy_df[voy_df["Vessel"] == ves_a].groupby("Equipment")["Liters"].sum().reset_index().rename(columns={"Liters": col_a})
                        df_b = voy_df[voy_df["Vessel"] == voy_df["Vessel"].unique()[0] if len(voy_df["Vessel"].unique()) == 1 else ves_b].groupby("Equipment")["Liters"].sum().reset_index().rename(columns={"Liters": col_b}) # safeguard
                        
                        comp_table = pd.DataFrame({"Equipment": equipments})
                        comp_table = pd.merge(comp_table, df_a, on="Equipment", how="left").fillna(0)
                        comp_table = pd.merge(comp_table, df_b, on="Equipment", how="left").fillna(0)
                        
                        diff = comp_table[col_b] - comp_table[col_a]
                        comp_table["Difference (L)"] = diff.apply(lambda x: f"+{x:.1f}" if x > 0 else f"{x:.1f}")
                        
                        st.dataframe(comp_table, use_container_width=True, hide_index=True)
                        
                        tot_a = voy_df[voy_df["Vessel"] == ves_a]["Liters"].sum()
                        tot_b = voy_df[voy_df["Vessel"] == ves_b]["Liters"].sum()
                        st.info(f"**Total Consumption:** {ves_a} burned **{tot_a:.1f} L** vs {ves_b} burned **{tot_b:.1f} L**.")
            else:
                st.info("No voyages available for comparison yet.")
    else:
        st.info("Not enough consumption data logged yet to run comparisons.")

    st.markdown("---")
    with st.expander("🔐 View Immutable Master Database & Audit History (Includes Voided & Deleted Records)"):
        st.dataframe(st.session_state.ledger, use_container_width=True, hide_index=True)

    # --- OWNER-ONLY PASSWORD MANAGEMENT ---
    if st.session_state.user_role == "Owner":
        st.markdown("---")
        st.subheader("🔑 Owner Security Settings (Manage Passwords)")
        st.markdown("Change the Assistant PIN or your Owner PIN anytime.")
        
        sec_col1, sec_col2 = st.columns(2)
        
        with sec_col1:
            with st.form("change_assistant_pin_form"):
                st.markdown("**Change Assistant PIN**")
                cur_a = st.session_state.pins["assistant_pin"]
                new_assist_pin = st.text_input("New 4-Digit Assistant PIN", value=cur_a, max_chars=4)
                if st.form_submit_button("💾 Update Assistant PIN"):
                    if len(new_assist_pin) != 4 or not new_assist_pin.isdigit():
                        st.error("🚨 Assistant PIN must be strictly 4 numeric digits.")
                    else:
                        st.session_state.pins["assistant_pin"] = new_assist_pin
                        save_pins(st.session_state.pins)
                        st.success(f"✅ Assistant PIN updated to {new_assist_pin}!")
                        
        with sec_col2:
            with st.form("change_owner_pin_form"):
                st.markdown("**Change Owner PIN**")
                cur_o = st.session_state.pins["owner_pin"]
                new_owner_pin = st.text_input("New 6-Digit Owner PIN", value=cur_o, max_chars=6)
                if st.form_submit_button("💾 Update Owner PIN"):
                    if len(new_owner_pin) != 6 or not new_owner_pin.isdigit():
                        st.error("🚨 Owner PIN must be strictly 6 numeric digits.")
                    else:
                        st.session_state.pins["owner_pin"] = new_owner_pin
                        st.session_state.recovered_login = False
                        save_pins(st.session_state.pins)
                        st.success(f"✅ Owner PIN updated to {new_owner_pin}!")

# === END OF CODE ===
