import os
import json
import hashlib
import secrets
from datetime import datetime

USERS_FILE = "data/users.json"
LOGS_FILE = "data/activity_logs.json"

class AuthManager:
    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self._initialize_default_admin()

    def _hash_password(self, password: str, salt: str = None) -> tuple[str, str]:
        """Hashes password using PBKDF2 HMAC-SHA256 with cryptographic salt."""
        if not salt:
            salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            salt.encode('utf-8'), 
            100000
        ).hex()
        return pwd_hash, salt

    def _initialize_default_admin(self):
        """Creates the initial admin account if no users exist."""
        if not os.path.exists(USERS_FILE):
            pwd_hash, salt = self._hash_password("admin123")
            default_users = {
                "admin": {
                    "username": "admin",
                    "full_name": "System Administrator",
                    "role": "admin",
                    "password_hash": pwd_hash,
                    "salt": salt,
                    "created_at": datetime.now().strftime("%d-%m-%Y %I:%M:%S %p")
                }
            }
            self._save_users(default_users)
            self.log_activity("admin", "admin", "System Initialized with default admin account")

    def _load_users(self) -> dict:
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_users(self, users: dict):
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)

    def authenticate(self, username: str, password: str) -> dict | None:
        """Verifies credentials and returns user metadata on success."""
        users = self._load_users()
        user = users.get(username.strip().lower())
        if not user:
            return None
        
        calc_hash, _ = self._hash_password(password, user["salt"])
        if secrets.compare_digest(calc_hash, user["password_hash"]):
            return {
                "username": user["username"],
                "full_name": user["full_name"],
                "role": user["role"]
            }
        return None

    def add_user(self, username: str, full_name: str, password: str, role: str, actor_username: str) -> tuple[bool, str]:
        """Creates a new user account (Admin only)."""
        clean_user = username.strip().lower()
        if not clean_user or not password:
            return False, "Username and Password cannot be empty."
        
        users = self._load_users()
        if clean_user in users:
            return False, f"User '{clean_user}' already exists."

        pwd_hash, salt = self._hash_password(password)
        users[clean_user] = {
            "username": clean_user,
            "full_name": full_name.strip() or clean_user,
            "role": role.lower(),
            "password_hash": pwd_hash,
            "salt": salt,
            "created_at": datetime.now().strftime("%d-%m-%Y %I:%M:%S %p")
        }
        self._save_users(users)
        self.log_activity(actor_username, "admin", f"Added user '{clean_user}' with role '{role}'")
        return True, f"User '{clean_user}' created successfully."

    def delete_user(self, target_username: str, actor_username: str) -> tuple[bool, str]:
        """Deletes a user account with safety checks against self-deletion or removing the sole admin."""
        clean_target = target_username.strip().lower()
        clean_actor = actor_username.strip().lower()

        if clean_target == clean_actor:
            return False, "You cannot delete your own active account."

        users = self._load_users()
        if clean_target not in users:
            return False, f"User '{clean_target}' does not exist."

        # Verify not deleting the last remaining admin
        admins = [u for u in users.values() if u.get("role") == "admin"]
        if users[clean_target].get("role") == "admin" and len(admins) <= 1:
            return False, "Cannot delete the only remaining admin account."

        del users[clean_target]
        self._save_users(users)
        self.log_activity(clean_actor, "admin", f"Deleted user '{clean_target}'")
        return True, f"User '{clean_target}' deleted successfully."

    def list_users(self) -> list[dict]:
        """Returns clean public records of all registered users."""
        users = self._load_users()
        return [
            {
                "Username": u["username"],
                "Full Name": u["full_name"],
                "Role": u["role"].capitalize(),
                "Created Date": u.get("created_at", "N/A")
            }
            for u in users.values()
        ]

    def log_activity(self, username: str, role: str, action: str, details: str = ""):
        """Appends an activity event to the permanent audit log."""
        logs = []
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, "r") as f:
                    logs = json.load(f)
            except Exception:
                logs = []

        entry = {
            "timestamp": datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
            "username": username,
            "role": role,
            "action": action,
            "details": details
        }
        logs.insert(0, entry)  # Prepend newest logs first
        
        # Retain last 2,000 log events
        if len(logs) > 2000:
            logs = logs[:2000]

        with open(LOGS_FILE, "w") as f:
            json.dump(logs, f, indent=2)

    def get_activity_logs(self) -> list[dict]:
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []