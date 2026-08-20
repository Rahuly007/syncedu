import streamlit as st
import pandas as pd
import json
import os
import shutil
import hashlib
from datetime import datetime
from modules.student_tracker import StudentTracker
from modules.timetable_tracker import TimetableTracker
from modules.auth_manager import AuthManager

st.set_page_config(page_title="Academic & Timetable Diff Tracker", layout="wide")

auth = AuthManager()
BOOKMARKS_FILE = "data/sheet_bookmarks.json"
TASKS_DIR = "data/tasks"
os.makedirs(TASKS_DIR, exist_ok=True)

# =========================================================
# HELPER FUNCTIONS
# =========================================================
def get_scoped_task_file(module_type, baseline_filename):
    safe_name = baseline_filename.replace(".json", "")
    return os.path.join(TASKS_DIR, f"{module_type}_tasks_{safe_name}.json")

def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json_file(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def make_task_signature(*args):
    raw = "___".join([str(a).strip() for a in args])
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]

def delete_snapshot_with_backup(snapshot_dir, filename):
    filepath = os.path.join(snapshot_dir, filename)
    if os.path.exists(filepath):
        backup_dir = os.path.join(snapshot_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"backup_{filename}")
        shutil.copy2(filepath, backup_path)
        os.remove(filepath)
        return backup_path
    return None

def extract_sheet_id(url_or_id):
    s = str(url_or_id).strip()
    if "/d/" in s:
        return s.split("/d/")[1].split("/")[0]
    return s

# =========================================================
# AUTHENTICATION GUARD & LOGIN SCREEN
# =========================================================
if "authenticated_user" not in st.session_state:
    st.session_state["authenticated_user"] = None

if not st.session_state["authenticated_user"]:
    st.title("Academic & Timetable Tracker Portal")
    login_col1, login_col2, login_col3 = st.columns([1, 1.2, 1])

    with login_col2:
        st.markdown("### Sign In to Continue")
        with st.form("login_form"):
            username_input = st.text_input("Username", placeholder="e.g. admin or rhy01")
            password_input = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Sign In", use_container_width=True)

            if submit_login:
                user = auth.authenticate(username_input, password_input)
                if user:
                    st.session_state["authenticated_user"] = user
                    auth.log_activity(user["username"], user["role"], "User Logged In")
                    st.success(f"Welcome back, {user['full_name']}!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        st.info("Default Admin account: `admin` | Password: `admin123`")
    st.stop()

# =========================================================
# LOGGED IN SIDEBAR HEADER
# =========================================================
current_user = st.session_state["authenticated_user"]
is_admin = current_user.get("role") == "admin"

with st.sidebar:
    st.markdown(f"**Logged in as:** {current_user['full_name']}")
    st.caption(f"Role: **{current_user['role'].upper()}** (`{current_user['username']}`)")
    if st.button("Log Out", use_container_width=True, key="btn_logout"):
        auth.log_activity(current_user["username"], current_user["role"], "User Logged Out")
        st.session_state["authenticated_user"] = None
        st.rerun()
    st.divider()

# =========================================================
# MAIN APP TABS ROUTING
# =========================================================
st.title("Academic Master Data & Timetable Tracker")

tab_titles = ["Student Master Data Tracker", "Timetable XML Tracker"]
if is_admin:
    tab_titles.append("Admin Control & Audit Logs")

tabs = st.tabs(tab_titles)
tab1, tab2 = tabs[0], tabs[1]
tab_admin = tabs[2] if is_admin else None


# =========================================================
# TAB 1: STUDENT DATA TRACKER
# =========================================================
with tab1:
    st.subheader("Student Data Change Detection (Google Sheet / Excel)")
    student_engine = StudentTracker()

    if "current_student_df" not in st.session_state:
        st.session_state["current_student_df"] = student_engine.load_current_working_copy()

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("**Method A: Fetch Live via Google OAuth**")

        saved_bookmarks = load_json_file(BOOKMARKS_FILE)
        preset_options = ["-- Select Saved Bookmark --"] + list(saved_bookmarks.keys())

        if "student_sheet_url_input" not in st.session_state:
            st.session_state["student_sheet_url_input"] = ""

        def on_bookmark_change():
            chosen = st.session_state.get("student_sheet_preset_select")
            if chosen and chosen != "-- Select Saved Bookmark --":
                st.session_state["student_sheet_url_input"] = saved_bookmarks.get(chosen, "")

        b_col1, b_col2 = st.columns([3, 1])
        with b_col1:
            preset_choice = st.selectbox(
                "Quick Select Bookmark:", 
                preset_options, 
                key="student_sheet_preset_select",
                on_change=on_bookmark_change
            )
        with b_col2:
            if preset_choice != "-- Select Saved Bookmark --":
                with st.popover("Delete"):
                    st.warning(f"Delete bookmark '{preset_choice}'?")
                    if st.button("Confirm Delete", key="btn_del_bookmark"):
                        if preset_choice in saved_bookmarks:
                            del saved_bookmarks[preset_choice]
                            save_json_file(BOOKMARKS_FILE, saved_bookmarks)
                            auth.log_activity(current_user["username"], current_user["role"], f"Deleted Bookmark '{preset_choice}'")
                            st.session_state["student_sheet_url_input"] = ""
                            st.success("Bookmark deleted!")
                            st.rerun()

        sheet_input_raw = st.text_input(
            "Google Sheet URL or ID:", 
            key="student_sheet_url_input",
            placeholder="Paste Google Sheet URL or ID here"
        )
        clean_sheet_id = extract_sheet_id(sheet_input_raw)

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            fetch_clicked = st.button("Fetch Live Sheet via OAuth", key="btn_fetch_student_oauth")
        with btn_col2:
            with st.popover("Bookmark This Sheet"):
                bookmark_name = st.text_input("Bookmark Name:", placeholder="e.g. Master CE Odd 2026", key="bm_name_input")
                if st.button("Save Bookmark", key="btn_save_new_bm"):
                    if bookmark_name and clean_sheet_id:
                        saved_bookmarks[bookmark_name] = clean_sheet_id
                        save_json_file(BOOKMARKS_FILE, saved_bookmarks)
                        auth.log_activity(current_user["username"], current_user["role"], f"Added Bookmark '{bookmark_name}'")
                        st.success(f"Saved '{bookmark_name}'!")
                        st.rerun()
                    else:
                        st.warning("Please provide a name and valid link/ID.")

        if fetch_clicked:
            if clean_sheet_id:
                try:
                    with st.spinner("Authenticating and fetching from Google Drive..."):
                        bytes_data = student_engine.fetch_google_sheet_as_bytes(clean_sheet_id)
                        df = student_engine.parse_student_data(bytes_data)
                        st.session_state["current_student_df"] = df
                        student_engine.save_current_working_copy(df)
                        auth.log_activity(current_user["username"], current_user["role"], "Fetched Google Sheet via OAuth", f"Sheet ID: {clean_sheet_id[:12]}... Records: {len(df)}")
                        st.success(f"Fetched & parsed {len(df)} records (Saved locally)!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Google OAuth Fetch Error: {e}")
                    st.info("You can use the local XLSX upload on the right as a fallback.")
            else:
                st.warning("Please paste or select a Google Sheet ID.")

    with col2:
        st.markdown("**Method B: Local Upload Fallback**")
        uploaded_excel = st.file_uploader("Upload .xlsx Workbook", type=["xlsx", "xls"], key="student_excel_uploader")
        if uploaded_excel is not None:
            try:
                df = student_engine.parse_student_data(uploaded_excel)
                st.session_state["current_student_df"] = df
                student_engine.save_current_working_copy(df)
                auth.log_activity(current_user["username"], current_user["role"], "Uploaded Local Student Excel File", f"File: {uploaded_excel.name} ({len(df)} records)")
                st.success(f"Loaded {len(df)} records from file (Saved locally)!")
            except Exception as e:
                st.error(f"Error parsing Excel file: {e}")

    # Process Diff & History
    current_df = st.session_state.get("current_student_df")
    if current_df is not None:
        all_snapshots = student_engine.list_snapshots()
        st.divider()

        st.markdown("### Snapshot Comparison & History")
        compare_col1, compare_col2 = st.columns([2, 1])

        with compare_col1:
            if all_snapshots:
                sel_c1, sel_c2 = st.columns([4, 1])
                with sel_c1:
                    baseline_choice = st.selectbox("Select Baseline Snapshot to Compare Against:", ["-- Most Recent Snapshot --"] + all_snapshots, key="student_baseline_select")
                    baseline_file = all_snapshots[0] if baseline_choice == "-- Most Recent Snapshot --" else baseline_choice
                with sel_c2:
                    with st.popover("Delete Baseline"):
                        st.error(f"Delete `{baseline_file}`?")
                        st.caption("A safety backup will be created in `data/student_snapshots/backups/` before deletion.")
                        if st.button("Confirm Delete", key="btn_del_student_baseline"):
                            b_path = delete_snapshot_with_backup(student_engine.snapshot_dir, baseline_file)
                            auth.log_activity(current_user["username"], current_user["role"], f"Deleted Student Baseline '{baseline_file}'")
                            st.success(f"Deleted! Backup created at `{b_path}`")
                            st.rerun()
            else:
                baseline_file = None
                st.info("No prior baseline snapshots found. Save this version to start tracking changes.")

        with compare_col2:
            indian_datetime_label = datetime.now().strftime("%d-%m-%Y_%I-%M-%S_%p")
            save_label = st.text_input("Snapshot Label", value=indian_datetime_label, key="student_snapshot_label_input")
            if st.button("Save Current Data as New Baseline Snapshot", key="btn_save_student_baseline"):
                path = student_engine.save_snapshot(current_df, label=save_label)
                auth.log_activity(current_user["username"], current_user["role"], "Saved New Student Baseline Snapshot", f"Label: {save_label}")
                st.success(f"Saved snapshot to `{path}`")
                st.rerun()

        if baseline_file:
            old_df = student_engine.load_snapshot(baseline_file)
            added, removed, modified = student_engine.compare_snapshots(old_df, current_df)

            student_task_file = get_scoped_task_file("student", baseline_file)
            student_task_state = load_json_file(student_task_file)

            sem_options = ["All Semesters"] + sorted([str(s) for s in current_df["semester"].dropna().unique()])
            selected_sem = st.selectbox("Filter Student Data by Semester:", sem_options, index=0, key="student_sem_filter_select")

            if selected_sem != "All Semesters":
                if not modified.empty and "semester" in modified.columns:
                    modified = modified[modified["semester"] == selected_sem]
                if not added.empty and "semester" in added.columns:
                    added = added[added["semester"] == selected_sem]
                if not removed.empty and "semester" in removed.columns:
                    removed = removed[removed["semester"] == selected_sem]

            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("Modified Records (Batch/Elective)", len(modified))
            m_col2.metric("New Admissions / Entries", len(added))
            m_col3.metric("Removed / Cancelled", len(removed))

            # 1. Modified Allocations Checklist
            st.markdown("#### 1. Modified Allocations Checklist (Batch / Elective / Class)")
            if not modified.empty:
                modified["_sig"] = modified.apply(lambda r: make_task_signature("mod", r.get("student_id"), r.get("changes_summary")), axis=1)
                modified["Done in ERP?"] = modified["_sig"].apply(lambda s: student_task_state.get(s, {}).get("done", False))
                modified["Action Notes"] = modified["_sig"].apply(lambda s: student_task_state.get(s, {}).get("notes", ""))

                cols_order = ["Done in ERP?", "student_id", "name", "semester", "class", "batch", "changes_summary", "Action Notes", "_sig"]
                edited_mod = st.data_editor(
                    modified[[c for c in cols_order if c in modified.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when updated in ERP/Attendance"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Updated in portal, notified student"),
                        "_sig": None
                    },
                    disabled=["student_id", "name", "semester", "class", "batch", "changes_summary"],
                    hide_index=True,
                    use_container_width=True,
                    key="student_task_editor_modified"
                )
                for _, r in edited_mod.iterrows():
                    student_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(student_task_file, student_task_state)
            else:
                st.info("No modifications detected.")

            # 2. Newly Added Students Checklist
            st.markdown("#### 2. Newly Added Students Checklist")
            if not added.empty:
                added["_sig"] = added.apply(lambda r: make_task_signature("add", r.get("student_id"), r.get("class"), r.get("batch")), axis=1)
                added["Done in ERP?"] = added["_sig"].apply(lambda s: student_task_state.get(s, {}).get("done", False))
                added["Action Notes"] = added["_sig"].apply(lambda s: student_task_state.get(s, {}).get("notes", ""))

                cols_order = ["Done in ERP?", "student_id", "name", "semester", "branch", "class", "batch", "Action Notes", "_sig"]
                edited_add = st.data_editor(
                    added[[c for c in cols_order if c in added.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when added in ERP/Attendance"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Enrolled in ERP, added to class list"),
                        "_sig": None
                    },
                    disabled=["student_id", "name", "semester", "branch", "class", "batch"],
                    hide_index=True,
                    use_container_width=True,
                    key="student_task_editor_added"
                )
                for _, r in edited_add.iterrows():
                    student_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(student_task_file, student_task_state)
            else:
                st.info("No newly added students.")

            # 3. Removed Students Checklist
            st.markdown("#### 3. Removed Students Checklist")
            if not removed.empty:
                removed["_sig"] = removed.apply(lambda r: make_task_signature("rem", r.get("student_id"), r.get("class")), axis=1)
                removed["Done in ERP?"] = removed["_sig"].apply(lambda s: student_task_state.get(s, {}).get("done", False))
                removed["Action Notes"] = removed["_sig"].apply(lambda s: student_task_state.get(s, {}).get("notes", ""))

                cols_order = ["Done in ERP?", "student_id", "name", "semester", "branch", "class", "batch", "Action Notes", "_sig"]
                edited_rem = st.data_editor(
                    removed[[c for c in cols_order if c in removed.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when removed/cancelled in ERP"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Cancelled in ERP, removed from registers"),
                        "_sig": None
                    },
                    disabled=["student_id", "name", "semester", "branch", "class", "batch"],
                    hide_index=True,
                    use_container_width=True,
                    key="student_task_editor_removed"
                )
                for _, r in edited_rem.iterrows():
                    student_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(student_task_file, student_task_state)
            else:
                st.info("No removed students.")


# =========================================================
# TAB 2: TIMETABLE TRACKER
# =========================================================
with tab2:
    st.subheader("aSc Timetable XML Change Detection")
    tt_engine = TimetableTracker()

    if "current_tt_df" not in st.session_state:
        st.session_state["current_tt_df"] = tt_engine.load_current_working_copy()

    uploaded_xml = st.file_uploader("Upload Newly Exported aSc Timetable XML File", type=["xml"], key="tt_xml_uploader_input")

    if uploaded_xml is not None:
        try:
            tt_df = tt_engine.parse_asc_xml(uploaded_xml)
            st.session_state["current_tt_df"] = tt_df
            tt_engine.save_current_working_copy(tt_df)
            auth.log_activity(current_user["username"], current_user["role"], "Uploaded Timetable XML File", f"File: {uploaded_xml.name} ({len(tt_df)} slots)")
            st.success(f"Parsed {len(tt_df)} scheduled slots from XML (Saved locally)!")
        except Exception as e:
            st.error(f"Error parsing Timetable XML: {e}")

    current_tt_df = st.session_state.get("current_tt_df")
    if current_tt_df is not None:
        all_tt_snapshots = tt_engine.list_snapshots()
        st.divider()

        tt_col1, tt_col2 = st.columns([2, 1])
        with tt_col1:
            if all_tt_snapshots:
                t_sel1, t_sel2 = st.columns([4, 1])
                with t_sel1:
                    baseline_tt = st.selectbox("Select Baseline Timetable to Compare Against:", ["-- Most Recent Timetable --"] + all_tt_snapshots, key="tt_baseline_select")
                    baseline_tt_file = all_tt_snapshots[0] if baseline_tt == "-- Most Recent Timetable --" else baseline_tt
                with t_sel2:
                    with st.popover("Delete Baseline"):
                        st.error(f"Delete `{baseline_tt_file}`?")
                        st.caption("A safety backup will be created in `data/timetable_snapshots/backups/` before deletion.")
                        if st.button("Confirm Delete", key="btn_del_tt_baseline"):
                            b_path = delete_snapshot_with_backup(tt_engine.snapshot_dir, baseline_tt_file)
                            auth.log_activity(current_user["username"], current_user["role"], f"Deleted Timetable Baseline '{baseline_tt_file}'")
                            st.success(f"Deleted! Backup created at `{b_path}`")
                            st.rerun()
            else:
                baseline_tt_file = None
                st.info("No prior timetable baseline found. Save this file as a baseline first.")

        with tt_col2:
            indian_tt_label = datetime.now().strftime("%d-%m-%Y_%I-%M-%S_%p")
            tt_label = st.text_input("Timetable Version Label", value=indian_tt_label, key="tt_snapshot_label_input")
            if st.button("Save Current Timetable as Baseline", key="btn_save_tt_baseline"):
                saved_path = tt_engine.save_snapshot(current_tt_df, label=tt_label)
                auth.log_activity(current_user["username"], current_user["role"], "Saved New Timetable Baseline Snapshot", f"Label: {tt_label}")
                st.success(f"Saved baseline to `{saved_path}`")
                st.rerun()

        if baseline_tt_file:
            old_tt_df = tt_engine.load_snapshot(baseline_tt_file)
            added_tt, removed_tt, modified_tt = tt_engine.compare_snapshots(old_tt_df, current_tt_df)

            tt_task_file = get_scoped_task_file("tt", baseline_tt_file)
            tt_task_state = load_json_file(tt_task_file)

            if "semester_program" in current_tt_df.columns:
                available_tt_sems = ["All Programs & Semesters"] + sorted([str(s) for s in current_tt_df["semester_program"].dropna().unique()])
            else:
                available_tt_sems = ["All Programs & Semesters"]

            selected_tt_sem = st.selectbox("Filter Timetable by Program / Semester:", available_tt_sems, index=0, key="tt_sem_program_filter_select")

            if selected_tt_sem != "All Programs & Semesters":
                if not modified_tt.empty and "semester_program" in modified_tt.columns:
                    modified_tt = modified_tt[modified_tt["semester_program"] == selected_tt_sem]
                if not added_tt.empty and "semester_program" in added_tt.columns:
                    added_tt = added_tt[added_tt["semester_program"] == selected_tt_sem]
                if not removed_tt.empty and "semester_program" in removed_tt.columns:
                    removed_tt = removed_tt[removed_tt["semester_program"] == selected_tt_sem]

            tc1, tc2, tc3 = st.columns(3)
            tc1.metric("Rescheduled / Altered Slots", len(modified_tt))
            tc2.metric("Newly Added Slots", len(added_tt))
            tc3.metric("Removed / Cancelled Slots", len(removed_tt))

            # 1. Rescheduled Timetable Cards Checklist
            st.markdown("#### 1. Modified / Rescheduled Lecture Cards (Side-by-Side Detail)")
            if not modified_tt.empty:
                modified_tt["_sig"] = modified_tt.apply(
                    lambda r: make_task_signature("tt_mod", r.get("class"), r.get("group"), r.get("subject"), r.get("old_timing"), r.get("new_timing")), 
                    axis=1
                )
                modified_tt["Done in ERP?"] = modified_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("done", False))
                modified_tt["Action Notes"] = modified_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("notes", ""))

                cols_order = [
                    'Done in ERP?', 'semester_program', 'class', 'group', 'subject', 
                    'old_timing', 'new_timing', 'old_room', 'new_room', 
                    'old_teacher', 'new_teacher', 'changes_summary', 'Action Notes', '_sig'
                ]
                edited_tt_mod = st.data_editor(
                    modified_tt[[c for c in cols_order if c in modified_tt.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when updated in faculty/student schedule"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Informs faculty, room booked"),
                        "_sig": None
                    },
                    disabled=['semester_program', 'class', 'group', 'subject', 'old_timing', 'new_timing', 'old_room', 'new_room', 'old_teacher', 'new_teacher', 'changes_summary'],
                    hide_index=True,
                    use_container_width=True,
                    key="tt_task_editor_modified"
                )
                for _, r in edited_tt_mod.iterrows():
                    tt_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(tt_task_file, tt_task_state)
            else:
                st.info("No timetable modifications detected.")

            # 2. Newly Added Lecture Cards Checklist
            st.markdown("#### 2. New Lecture / Lab Cards Added")
            if not added_tt.empty:
                added_tt["_sig"] = added_tt.apply(
                    lambda r: make_task_signature("tt_add", r.get("class"), r.get("group"), r.get("subject"), r.get("day"), r.get("period")), 
                    axis=1
                )
                added_tt["Done in ERP?"] = added_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("done", False))
                added_tt["Action Notes"] = added_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("notes", ""))

                cols_order = ['Done in ERP?', 'semester_program', 'class', 'group', 'subject', 'teacher', 'classroom', 'day', 'period', 'duration', 'Action Notes', '_sig']
                edited_tt_add = st.data_editor(
                    added_tt[[c for c in cols_order if c in added_tt.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when timetable is published"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Added to master room chart"),
                        "_sig": None
                    },
                    disabled=['semester_program', 'class', 'group', 'subject', 'teacher', 'classroom', 'day', 'period', 'duration'],
                    hide_index=True,
                    use_container_width=True,
                    key="tt_task_editor_added"
                )
                for _, r in edited_tt_add.iterrows():
                    tt_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(tt_task_file, tt_task_state)
            else:
                st.info("No new lecture/lab cards added.")

            # 3. Removed Lecture Cards Checklist
            st.markdown("#### 3. Lecture / Lab Cards Removed")
            if not removed_tt.empty:
                removed_tt["_sig"] = removed_tt.apply(
                    lambda r: make_task_signature("tt_rem", r.get("class"), r.get("group"), r.get("subject"), r.get("day"), r.get("period")), 
                    axis=1
                )
                removed_tt["Done in ERP?"] = removed_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("done", False))
                removed_tt["Action Notes"] = removed_tt["_sig"].apply(lambda s: tt_task_state.get(s, {}).get("notes", ""))

                cols_order = ['Done in ERP?', 'semester_program', 'class', 'group', 'subject', 'teacher', 'classroom', 'day', 'period', 'duration', 'Action Notes', '_sig']
                edited_tt_rem = st.data_editor(
                    removed_tt[[c for c in cols_order if c in removed_tt.columns]],
                    column_config={
                        "Done in ERP?": st.column_config.CheckboxColumn("Done?", help="Check when cancelled in portal"),
                        "Action Notes": st.column_config.TextColumn("Notes", help="e.g. Cancelled, room freed"),
                        "_sig": None
                    },
                    disabled=['semester_program', 'class', 'group', 'subject', 'teacher', 'classroom', 'day', 'period', 'duration'],
                    hide_index=True,
                    use_container_width=True,
                    key="tt_task_editor_removed"
                )
                for _, r in edited_tt_rem.iterrows():
                    tt_task_state[r["_sig"]] = {"done": bool(r["Done in ERP?"]), "notes": str(r["Action Notes"])}
                save_json_file(tt_task_file, tt_task_state)
            else:
                st.info("No lecture/lab cards removed.")


# =========================================================
# TAB 3: ADMIN CONTROL & AUDIT LOGS (ADMIN ONLY)
# =========================================================
if is_admin and tab_admin is not None:
    with tab_admin:
        st.subheader("System Administration & User Management")

        admin_col1, admin_col2 = st.columns([1.2, 1.8])

        # --- User Creation & Deletion ---
        with admin_col1:
            st.markdown("#### User Accounts")
            user_list = auth.list_users()
            st.dataframe(pd.DataFrame(user_list), use_container_width=True, hide_index=True)

            with st.expander("➕ Add New User", expanded=False):
                with st.form("add_user_form"):
                    new_u = st.text_input("Username", placeholder="e.g. jdoe")
                    new_name = st.text_input("Full Name", placeholder="e.g. John Doe")
                    new_pwd = st.text_input("Password", type="password")
                    new_role = st.selectbox("Role", ["Staff / Faculty", "Admin"])
                    role_val = "admin" if new_role == "Admin" else "staff"
                    btn_submit_user = st.form_submit_button("Create Account", use_container_width=True)

                    if btn_submit_user:
                        ok, msg = auth.add_user(new_u, new_name, new_pwd, role_val, current_user["username"])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            with st.expander("🗑️ Delete User", expanded=False):
                with st.form("delete_user_form"):
                    del_candidate_options = [u["Username"] for u in user_list if u["Username"] != current_user["username"]]
                    target_to_del = st.selectbox("Select User to Remove", del_candidate_options if del_candidate_options else ["None available"])
                    btn_submit_del = st.form_submit_button("Delete User", use_container_width=True)

                    if btn_submit_del:
                        if target_to_del and target_to_del != "None available":
                            ok, msg = auth.delete_user(target_to_del, current_user["username"])
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

        # --- Audit Activity Logs ---
        with admin_col2:
            st.markdown("#### User Activity & Audit Logs")
            raw_logs = auth.get_activity_logs()
            if raw_logs:
                logs_df = pd.DataFrame(raw_logs)
                
                # Filter Logs by User or Action
                filter_c1, filter_c2 = st.columns([1, 1])
                with filter_c1:
                    user_filter = st.selectbox("Filter Log by User:", ["All Users"] + sorted(list(logs_df["username"].unique())))
                with filter_c2:
                    action_search = st.text_input("Search Action / Details:", placeholder="e.g. OAuth, Deleted")

                if user_filter != "All Users":
                    logs_df = logs_df[logs_df["username"] == user_filter]
                if action_search:
                    logs_df = logs_df[
                        logs_df["action"].str.contains(action_search, case=False, na=False) | 
                        logs_df["details"].str.contains(action_search, case=False, na=False)
                    ]

                st.dataframe(logs_df, use_container_width=True, hide_index=True)

                csv_logs = logs_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download Audit Logs (CSV)",
                    data=csv_logs,
                    file_name=f"audit_logs_{datetime.now().strftime('%d-%m-%Y')}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No activity logs recorded yet.")