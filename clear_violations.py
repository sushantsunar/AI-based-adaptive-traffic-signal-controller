import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "database" / "traffic.db"
VIOLATIONS_DIR = PROJECT_ROOT / "violations"


def clear_db():
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    for table in ["lane_violations", "lane_change_violations"]:
        try:
            cur.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass

    # Reset AUTOINCREMENT counters if present
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('lane_violations','lane_change_violations')")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def clear_images():
    if not VIOLATIONS_DIR.exists():
        return

    removed = 0
    for p in VIOLATIONS_DIR.glob("*.jpg"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    for p in VIOLATIONS_DIR.glob("*.jpeg"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    for p in VIOLATIONS_DIR.glob("*.png"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    print(f"Removed {removed} image(s) from {VIOLATIONS_DIR}")


def clear_memory_state():
    # Reset in-process caches if script is run in same interpreter session.
    try:
        from violation import lane_crossing, lane_change

        if hasattr(lane_crossing, "reset_state"):
            lane_crossing.reset_state()
        if hasattr(lane_change, "reset_state"):
            lane_change.reset_state()
    except Exception:
        pass


if __name__ == "__main__":
    clear_db()
    clear_images()
    clear_memory_state()
    print("Violation logs cleared.")

