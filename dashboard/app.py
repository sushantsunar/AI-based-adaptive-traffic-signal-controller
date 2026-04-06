from flask import Flask, render_template, Response, jsonify, send_from_directory, abort, request, redirect, url_for
from dashboard.shared_data import traffic_state
from flask_cors import CORS
import cv2
import sqlite3
import time
import threading
import atexit
import os

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "database", "traffic.db")
VIOLATIONS_DIR = os.path.join(BASE_DIR, "violations")
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")


class CameraStream:
    """Single-threaded reader for one video source to avoid FFmpeg decoder races."""

    def __init__(self, source_path, out_size=(320, 240), max_fps=15.0):
        self.source_path = source_path
        self.out_size = out_size
        self.cap = cv2.VideoCapture(source_path)

        src_fps = self.cap.get(cv2.CAP_PROP_FPS)
        fps = src_fps if src_fps and src_fps > 1 else 25.0
        fps = min(float(fps), float(max_fps)) if max_fps else float(fps)
        self.frame_interval = 1.0 / max(1.0, fps)

        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.latest_jpeg = None
        self.latest_raw = None
        self.frame_seq = 0
        self.running = True

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _reader_loop(self):
        next_frame_at = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            if now < next_frame_at:
                time.sleep(next_frame_at - now)
            next_frame_at += self.frame_interval

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
                if not ok or frame is None:
                    time.sleep(0.02)
                    continue

            frame_disp = cv2.resize(frame, self.out_size)
            ok, buf = cv2.imencode(".jpg", frame_disp)
            if not ok:
                continue

            with self.lock:
                self.latest_jpeg = buf.tobytes()
                self.latest_raw = frame
                self.frame_seq += 1
                self.cond.notify_all()

    def wait_jpeg(self, last_seq, timeout=1.0):
        with self.lock:
            # Wait for the first frame or for a new frame sequence.
            if self.latest_jpeg is None or self.frame_seq == last_seq:
                self.cond.wait(timeout=timeout)
            return self.frame_seq, self.latest_jpeg

    def get_raw_copy(self):
        with self.lock:
            if self.latest_raw is None:
                return None
            return self.latest_raw.copy()

    def stop(self):
        self.running = False
        with self.lock:
            self.cond.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap is not None:
            self.cap.release()


CAMERA_SOURCES = {
    "N": os.path.join(VIDEOS_DIR, "north.mp4"),
    "S": os.path.join(VIDEOS_DIR, "south.mp4"),
    "E": os.path.join(VIDEOS_DIR, "east.mp4"),
    "W": os.path.join(VIDEOS_DIR, "west.mp4"),
}

camera_streams = {d: CameraStream(path) for d, path in CAMERA_SOURCES.items()}


def _cleanup_streams():
    for stream in camera_streams.values():
        stream.stop()


atexit.register(_cleanup_streams)

live_count_cache = {"N": 0, "S": 0, "E": 0, "W": 0}
live_count_updated_at = 0.0
cache_lock = threading.Lock()


def gen_frames(direction):
    stream = camera_streams[direction]
    last_seq = -1
    while True:
        seq, jpeg = stream.wait_jpeg(last_seq, timeout=1.0)
        if jpeg is None:
            time.sleep(0.02)
            continue
        if seq == last_seq:
            continue
        last_seq = seq

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        )


@app.route("/video/<direction>")
def video_feed(direction):
    direction = direction.upper()
    if direction not in camera_streams:
        abort(404)
    resp = Response(gen_frames(direction), mimetype="multipart/x-mixed-replace; boundary=frame")
    # Avoid proxy/browser buffering adding latency.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


def _safe_count_dict(source):
    return {
        "N": int(source.get("N", 0)),
        "S": int(source.get("S", 0)),
        "E": int(source.get("E", 0)),
        "W": int(source.get("W", 0)),
    }


@app.route("/data")
def data():
    state = dict(traffic_state)
    state["live_vehicle_count"] = _safe_count_dict(state.get("live_vehicle_count", {}))
    state["vehicle_count"] = _safe_count_dict(state.get("vehicle_count", {}))
    return jsonify(state)


@app.route("/live-counts")
def live_counts():
    # Keep dashboard responsive: reuse algorithm-side counts (already ROI-filtered).
    counts = traffic_state.get("live_vehicle_count", {})
    safe = _safe_count_dict(counts)
    return jsonify(safe)


@app.route("/manual-switch", methods=["POST"])
def manual_switch():
    payload = request.get_json(silent=True) or {}
    direction = str(payload.get("direction", "")).upper()
    try:
        duration = int(payload.get("duration", 20))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "duration must be an integer"}), 400

    if direction not in {"N", "S", "E", "W"}:
        return jsonify({"ok": False, "error": "direction must be one of N,S,E,W"}), 400

    duration = max(5, min(duration, 90))
    traffic_state["manual_override"] = {
        "enabled": True,
        "direction": direction,
        "duration": duration,
    }
    return jsonify({"ok": True, "manual_override": traffic_state["manual_override"]})


@app.route("/manual-switch/clear", methods=["POST"])
def clear_manual_switch():
    traffic_state["manual_override"] = {
        "enabled": False,
        "direction": None,
        "duration": 20,
    }
    return jsonify({"ok": True, "manual_override": traffic_state["manual_override"]})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/violations")
def get_violations():
    selected_direction = request.args.get("direction", "ALL").upper()
    valid_directions = {"N", "S", "E", "W"}
    if selected_direction not in valid_directions and selected_direction != "ALL":
        selected_direction = "ALL"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    where_clause = ""
    params = ()
    if selected_direction != "ALL":
        where_clause = "WHERE direction = ?"
        params = (selected_direction,)

    cursor.execute(
        f"""
        SELECT
            kind,
            id,
            vehicle_id,
            direction,
            from_lane,
            to_lane,
            timestamp,
            image_path
        FROM (
            SELECT
                'lane_cross' AS kind,
                id,
                vehicle_id,
                direction,
                NULL AS from_lane,
                NULL AS to_lane,
                timestamp,
                image_path
            FROM lane_violations
            {where_clause}
            UNION ALL
            SELECT
                'lane_change' AS kind,
                id,
                vehicle_id,
                direction,
                from_lane,
                to_lane,
                timestamp,
                image_path
            FROM lane_change_violations
            {where_clause}
        )
        ORDER BY timestamp DESC
        LIMIT 20
        """,
        params + params,
    )

    rows = cursor.fetchall()
    conn.close()

    violations = []
    for r in rows:
        violations.append(
            {
                "kind": r[0],
                "id": r[1],
                "vehicle_id": r[2],
                "direction": r[3],
                "from_lane": r[4],
                "to_lane": r[5],
                "time": r[6],
                "image": r[7],
            }
        )

    return render_template(
        "violations.html",
        total=len(violations),
        violations=violations,
        selected_direction=selected_direction,
    )


@app.route("/violations/clear", methods=["POST"])
def clear_violations():
    # Clear DB rows.
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for table in ["lane_violations", "lane_change_violations"]:
        try:
            cur.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('lane_violations','lane_change_violations')")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

    # Clear saved evidence images.
    try:
        if os.path.isdir(VIOLATIONS_DIR):
            for name in os.listdir(VIOLATIONS_DIR):
                if name.lower().endswith((".jpg", ".jpeg", ".png")):
                    try:
                        os.remove(os.path.join(VIOLATIONS_DIR, name))
                    except OSError:
                        pass
    except Exception:
        pass

    # Best-effort: clear in-process caches so the next violation can fire immediately.
    try:
        from violation import lane_crossing, lane_change
        from tracking.tracker import reset_trackers

        if hasattr(lane_crossing, "reset_state"):
            lane_crossing.reset_state()
        if hasattr(lane_change, "reset_state"):
            lane_change.reset_state()
        # Also reset trackers: after clearing, stale IDs can prevent fresh lane-change confirmation.
        reset_trackers()
    except Exception:
        pass

    return redirect(url_for("get_violations", direction=request.args.get("direction", "ALL")))


@app.route("/violation-image/<path:filename>")
def violation_image(filename):
    return send_from_directory(VIOLATIONS_DIR, filename)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
