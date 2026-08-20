import os
import io
import json
from datetime import datetime
import pandas as pd
import requests

# Google OAuth & API client imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

class StudentTracker:
    def __init__(self, snapshot_dir="data/student_snapshots", credentials_path="credentials.json", token_path="token.json"):
        self.snapshot_dir = snapshot_dir
        self.credentials_path = credentials_path
        self.token_path = token_path
        os.makedirs(self.snapshot_dir, exist_ok=True)
        
        # Canonical mapping for semester sheets
        self.semester_sheets = {
            "1st Sem": ["B.Tech. 1stSem"],
            "3rd Sem": ["B.Tech. 3rdSem", "B.Tech. 3rdSem_D2D&IOT"],
            "5th Sem": ["B.Tech. 5thSem"],
            "7th Sem": ["B.Tech. 7thSem"]
        }

    # ==========================================
    # 1. Google OAuth 2.0 Ingestion
    # ==========================================
    
    def authenticate_google(self):
        """Authenticates user via OAuth 2.0 desktop flow with corrupted-token auto-recovery."""
        if not GOOGLE_AUTH_AVAILABLE:
            raise ImportError("Google API client packages are not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(f"Missing '{self.credentials_path}'. Place your Google Cloud OAuth client credentials JSON in the root folder.")

        creds = None

        # Check token.json and safely ignore/delete if empty or invalid
        if os.path.exists(self.token_path):
            try:
                if os.path.getsize(self.token_path) > 0:
                    creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
                else:
                    os.remove(self.token_path)
            except Exception:
                os.remove(self.token_path)
                creds = None

        # Refresh or initiate browser login
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())

        return build('drive', 'v3', credentials=creds)
    
    def fetch_google_sheet_as_bytes(self, spreadsheet_id):
        """Fetches Google Sheet with full Shared Drive / Team Drive support and HTTP fallback."""
        creds = self.get_credentials()
        
        # Method 1: Direct HTTP GET using OAuth 2.0 Bearer Token (Most reliable across Workspace drives)
        try:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            
            url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
            headers = {"Authorization": f"Bearer {creds.token}"}
            resp = requests.get(url, headers=headers)
            
            if resp.status_code == 200 and len(resp.content) > 1000:
                return io.BytesIO(resp.content)
        except Exception:
            pass

        # Method 2: Drive v3 API export with explicit Shared Drive flags
        try:
            drive_service = build('drive', 'v3', credentials=creds)
            request = drive_service.files().export_media(
                fileId=spreadsheet_id,
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            # Enable shared drive access
            request.uri += "&supportsAllDrives=true"
            
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            raise Exception(f"Unable to access sheet ({spreadsheet_id}). Ensure you logged in with your @ganpatuniversity.ac.in account and have view access. Details: {e}")

    # ==========================================
    # 2. Universal Sheet Parsing (.xlsx or Bytes)
    # ==========================================
    def _clean_str(self, val):
        if pd.isna(val):
            return ""
        s = str(val).strip()
        if s.endswith('.0') and s[:-2].isdigit():
            return s[:-2]
        return s

    def parse_student_data(self, file_source):
        """
        Parses student data from either:
        - A local file path (str)
        - An uploaded file object (Streamlit UploadedFile)
        - A BytesIO stream from Google Drive
        """
        xls = pd.ExcelFile(file_source)
        records = []

        for sem_label, sheets in self.semester_sheets.items():
            for sheet in sheets:
                if sheet not in xls.sheet_names:
                    continue
                df = pd.read_excel(xls, sheet_name=sheet)
                df.columns = [str(c).strip() for c in df.columns]

                # Dynamically resolve columns
                name_col = next((c for c in df.columns if 'name' in c.lower()), None)
                perm_enr_col = next((c for c in df.columns if 'permanent' in c.lower() or c.lower() in ['enrollment no.', 'enrollment number', 'enrollment no']), None)
                temp_enr_col = next((c for c in df.columns if 'temp' in c.lower()), None)
                branch_col = next((c for c in df.columns if 'branch' in c.lower()), None)
                class_col = next((c for c in df.columns if c.lower() == 'class'), None)
                batch_col = next((c for c in df.columns if c.lower() == 'batch'), None)
                e1_col = next((c for c in df.columns if any(k in c.lower() for k in ['subject e-5', 'subject e-1', 'e-3 alloted', 'e-1 subject'])), None)
                e2_col = next((c for c in df.columns if any(k in c.lower() for k in ['subject e-6', 'subject e-2', 'e-4 alloted', 'e-2 subject'])), None)

                for _, row in df.iterrows():
                    name = self._clean_str(row.get(name_col, ""))
                    if not name or name.lower() == 'nan':
                        continue

                    perm_enr = self._clean_str(row.get(perm_enr_col, ""))
                    temp_enr = self._clean_str(row.get(temp_enr_col, ""))
                    student_id = perm_enr if perm_enr else (temp_enr if temp_enr else name)

                    records.append({
                        "student_id": student_id,
                        "enrollment_no": perm_enr,
                        "temp_enrollment_no": temp_enr,
                        "name": name,
                        "semester": sem_label,
                        "branch": self._clean_str(row.get(branch_col, "")),
                        "class": self._clean_str(row.get(class_col, "")),
                        "batch": self._clean_str(row.get(batch_col, "")),
                        "elective_1": self._clean_str(row.get(e1_col, "")) if e1_col else "",
                        "elective_2": self._clean_str(row.get(e2_col, "")) if e2_col else "",
                        "source_sheet": sheet
                    })

        return pd.DataFrame(records)

    # ==========================================
    # 3. Snapshot & Diff Tracking Engine
    # ==========================================
    def get_latest_snapshot_file(self):
        files = sorted([os.path.join(self.snapshot_dir, f) for f in os.listdir(self.snapshot_dir) if f.endswith('.json')])
        return files[-1] if files else None

    def list_snapshots(self):
        """Returns only saved baseline snapshots (excluding current working copy)."""
        files = [
            f for f in os.listdir(self.snapshot_dir) 
            if f.endswith('.json') and not f.startswith("current_working_copy")
        ]
        return sorted(files, reverse=True)

    def save_snapshot(self, df_records, label=""):
        """Saves a permanent baseline snapshot."""
        if not label:
            label = datetime.now().strftime("%d-%m-%Y_%I-%M-%S_%p")
        
        # If label already ends with .json, use it; otherwise append .json
        clean_label = label.replace(".json", "")
        filename = f"{clean_label}.json"
        
        filepath = os.path.join(self.snapshot_dir, filename)
        df_records.to_json(filepath, orient="records", indent=2)
        return filepath

    def load_snapshot(self, filename_or_path):
        if not os.path.isabs(filename_or_path) and not filename_or_path.startswith("data/"):
            filename_or_path = os.path.join(self.snapshot_dir, filename_or_path)
        return pd.read_json(filename_or_path)

    def compare_snapshots(self, df_old, df_new):
        """
        Computes granular diffs between two student states.
        Returns: added_df, removed_df, modified_df
        """
        old_indexed = df_old.set_index("student_id")
        new_indexed = df_new.set_index("student_id")

        old_ids = set(old_indexed.index)
        new_ids = set(new_indexed.index)

        added_ids = new_ids - old_ids
        removed_ids = old_ids - new_ids
        common_ids = old_ids & new_ids

        added_df = new_indexed.loc[list(added_ids)].reset_index() if added_ids else pd.DataFrame()
        removed_df = old_indexed.loc[list(removed_ids)].reset_index() if removed_ids else pd.DataFrame()

        tracked_fields = ["class", "batch", "elective_1", "elective_2", "branch", "semester"]
        modifications = []

        for sid in common_ids:
            row_old = old_indexed.loc[sid]
            row_new = new_indexed.loc[sid]

            if isinstance(row_old, pd.DataFrame):
                row_old = row_old.iloc[0]
            if isinstance(row_new, pd.DataFrame):
                row_new = row_new.iloc[0]

            changes = []
            for field in tracked_fields:
                val_old = str(row_old.get(field, "")).strip()
                val_new = str(row_new.get(field, "")).strip()
                if val_old != val_new:
                    changes.append({
                        "field": field,
                        "old": val_old,
                        "new": val_new
                    })

            if changes:
                modifications.append({
                    "student_id": sid,
                    "name": row_new.get("name", ""),
                    "semester": row_new.get("semester", ""),
                    "class": row_new.get("class", ""),
                    "batch": row_new.get("batch", ""),
                    "changes_summary": ", ".join([f"{c['field'].replace('_', ' ').title()}: '{c['old']}' → '{c['new']}'" for c in changes]),
                    "detailed_changes": changes
                })

        modified_df = pd.DataFrame(modifications)
        return added_df, removed_df, modified_df
    
    def save_current_working_copy(self, df_records):
        """Persists the latest fetched data to disk so it survives browser restarts."""
        filepath = os.path.join(self.snapshot_dir, "current_working_copy.json")
        df_records.to_json(filepath, orient="records", indent=2)
        return filepath

    def load_current_working_copy(self):
        """Loads the persisted working copy if available."""
        filepath = os.path.join(self.snapshot_dir, "current_working_copy.json")
        if os.path.exists(filepath):
            try:
                return pd.read_json(filepath)
            except Exception:
                return None
        return None
    def fetch_google_sheet_as_bytes(self, spreadsheet_id):
        """Fetches Google Sheet with full Shared Drive / Team Drive support."""
        drive_service = self.authenticate_google()
        
        try:
            # 1. Drive v3 Export with Shared Drive support
            request = drive_service.files().export_media(
                fileId=spreadsheet_id,
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            file_stream.seek(0)
            return file_stream

        except Exception as drive_err:
            # 2. Fallback: Direct OAuth Bearer Token export
            creds = None
            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            
            if creds and creds.valid:
                url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
                headers = {"Authorization": f"Bearer {creds.token}"}
                resp = requests.get(url, headers=headers)
                if resp.status_code == 200:
                    return io.BytesIO(resp.content)
            
            raise drive_err