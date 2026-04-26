import os
import sqlite3
import secrets
import datetime
from pathlib import Path

# Always resolve DB relative to project root (not current working directory).
_BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = str(_BASE_DIR / "database" / "traffic.db")

def get_connection():
    os.makedirs(str(_BASE_DIR / "database"), exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lane_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER,
            direction TEXT,
            timestamp TEXT,
            image_path TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lane_change_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER,
            direction TEXT,
            from_lane TEXT,
            to_lane TEXT,
            timestamp TEXT,
            image_path TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()

    # Bootstrap an initial admin user on first run.
    # - If DASHBOARD_ADMIN_PASSWORD is set, use it.
    # - Otherwise generate a random password and print it once to the console.
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = int(cursor.fetchone()[0] or 0)
        if user_count == 0:
            from werkzeug.security import generate_password_hash

            username = os.environ.get("DASHBOARD_ADMIN_USER", "admin").strip() or "admin"
            env_password = os.environ.get("DASHBOARD_ADMIN_PASSWORD")
            if env_password is not None and str(env_password).strip() != "":
                password = str(env_password)
                password_note = "(from DASHBOARD_ADMIN_PASSWORD)"
            else:
                password = secrets.token_urlsafe(12)
                password_note = "(auto-generated)"

            cursor.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), datetime.datetime.utcnow().isoformat() + "Z"),
            )
            conn.commit()
            print("\n=== Dashboard login created ===")
            print(f"Username: {username}")
            print(f"Password: {password} {password_note}")
            print("Set DASHBOARD_ADMIN_PASSWORD to control this.\n")
    except Exception:
        # Best-effort; don't break the main app if auth bootstrap fails.
        pass

    conn.close()

def insert_violation(vehicle_id, direction, timestamp, image_path):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO lane_violations
        (vehicle_id, direction, timestamp, image_path)
        VALUES (?, ?, ?, ?)
    """, (vehicle_id, direction, timestamp, image_path))

    conn.commit()
    conn.close()


def insert_lane_change_violation(vehicle_id, direction, from_lane, to_lane, timestamp, image_path):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO lane_change_violations
        (vehicle_id, direction, from_lane, to_lane, timestamp, image_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (vehicle_id, direction, from_lane, to_lane, timestamp, image_path))

    conn.commit()
    conn.close()
