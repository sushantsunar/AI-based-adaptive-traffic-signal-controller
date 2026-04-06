import os
import sqlite3
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

    conn.commit()
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
