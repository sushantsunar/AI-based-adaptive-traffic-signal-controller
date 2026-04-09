from flask import Flask, render_template, Response, jsonify, abort
from flask_cors import CORS
import threading
import time
import os
import cv2
import atexit

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "dashboard", "templates")
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")

app = Flask(__name__, template_folder=TEMPLATE_DIR)
CORS(app)

CAMERA_SOURCES = {
    "N": os.path.join(VIDEOS_DIR, "north.mp4"),
    "S": os.path.join(VIDEOS_DIR, "south.mp4"),
    "E": os.path.join(VIDEOS_DIR, "east.mp4"),
    "W": os.path.join(VIDEOS_DIR, "west.mp4"),
}

SIMULATION_SEQUENCE = [
    ("N", 12),
    ("YELLOW_N", 3),
    ("ALL_RED", 2),
    ("E", 12),
    ("YELLOW_E", 3),
    ("ALL_RED", 2),
    ("S", 12),
    ("YELLOW_S", 3),
    ("ALL_RED", 2),
    ("W", 12),
    ("YELLOW_W", 3),
    ("ALL_RED", 2),
]

class DemoCameraStream:
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
            ok, buf = cv2.imencode('.jpg', frame_disp)
            if not ok:
                continue

            with self.lock:
                self.latest_jpeg = buf.tobytes()
                self.latest_raw = frame
                self.frame_seq += 1
                self.cond.notify_all()

    def wait_jpeg(self, last_seq, timeout=1.0):
        with self.lock:
            if self.latest_jpeg is None or self.frame_seq == last_seq:
                self.cond.wait(timeout=timeout)
            return self.frame_seq, self.latest_jpeg

    def stop(self):
        self.running = False
        with self.lock:
            self.cond.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap is not None:
            self.cap.release()

camera_streams = {
    direction: DemoCameraStream(path)
    for direction, path in CAMERA_SOURCES.items()
}

simulation_state = {
    "current_green": "N",
    "remaining_time": SIMULATION_SEQUENCE[0][1],
    "cycle": 1,
    "phase_index": 0,
}
state_lock = threading.Lock()

running = True


def cleanup_streams():
    global running
    running = False
    for stream in camera_streams.values():
        stream.stop()

atexit.register(cleanup_streams)


def simulation_loop():
    while running:
        with state_lock:
            if simulation_state["remaining_time"] <= 0:
                simulation_state["phase_index"] = (simulation_state["phase_index"] + 1) % len(SIMULATION_SEQUENCE)
                phase, duration = SIMULATION_SEQUENCE[simulation_state["phase_index"]]
                simulation_state["current_green"] = phase
                simulation_state["remaining_time"] = duration
                if simulation_state["phase_index"] == 0:
                    simulation_state["cycle"] += 1

        time.sleep(1.0)
        with state_lock:
            simulation_state["remaining_time"] = max(0, simulation_state["remaining_time"] - 1)


def is_direction_active(direction, phase):
    return phase == direction or phase == f"YELLOW_{direction}"


def gen_demo_frames(direction):
    stream = camera_streams[direction]
    last_seq = -1
    frozen_jpeg = None
    while running:
        with state_lock:
            phase = simulation_state["current_green"]

        active = is_direction_active(direction, phase)
        if active:
            seq, jpeg = stream.wait_jpeg(last_seq, timeout=1.0)
            if jpeg is None:
                time.sleep(0.02)
                continue
            last_seq = seq
            frozen_jpeg = jpeg
        else:
            if frozen_jpeg is None:
                seq, jpeg = stream.wait_jpeg(last_seq, timeout=1.0)
                if jpeg is None:
                    time.sleep(0.02)
                    continue
                frozen_jpeg = jpeg
            time.sleep(0.05)
            jpeg = frozen_jpeg

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")


@app.route("/")
def index():
    return render_template("demo.html")


@app.route("/demo/state")
def demo_state():
    with state_lock:
        return jsonify({
            "current_green": simulation_state["current_green"],
            "remaining_time": simulation_state["remaining_time"],
            "cycle": simulation_state["cycle"],
        })


@app.route("/demo/video/<direction>")
def video_feed(direction):
    direction = direction.upper()
    if direction not in camera_streams:
        abort(404)
    resp = Response(gen_demo_frames(direction), mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


if __name__ == "__main__":
    simulator = threading.Thread(target=simulation_loop, daemon=True)
    simulator.start()
    app.run(debug=False, port=5001, use_reloader=False)
