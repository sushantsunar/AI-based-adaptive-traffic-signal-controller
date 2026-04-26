import cv2
import threading
import time
import traceback

from detection.yolo_detector import detect_vehicles
from detection.emergency_detection import detect_emergency
from tracking.tracker import track_objects
from data.buffer import update_buffer, get_average_density
from algorithm.waps import calculate_priority, dynamic_gmin, calculate_green_time
from traffic_signal.controller import run_signal
from dashboard.shared_data import traffic_state
from utils.lane_roi import load_lane_rois, filter_tracks_by_roi
from utils.lane_regions import load_lane_regions, lane_for_track_bottom_center

from violation.lane_crossing import check_lane_crossing
from violation.lane_change import check_lane_change_violations
from database.db import init_db

init_db()

videos = {
    "N": cv2.VideoCapture("videos/north.mp4"),
    "S": cv2.VideoCapture("videos/south.mp4"),
    "E": cv2.VideoCapture("videos/east.mp4"),
    "W": cv2.VideoCapture("videos/west.mp4"),
}

waiting_time = {"N": 0, "S": 0, "E": 0, "W": 0}
lane_importance = {"N": 2, "S": 2, "E": 1, "W": 1}
lane_rois = load_lane_rois()
lane_regions = load_lane_regions()

for d in ["N", "S", "E", "W"]:
    if len(lane_regions.get(d, {})) < 2:
        print(f"Lane-change polygons not configured for {d} (need >=2 lanes in config/lane_regions.json).")


def fixed_time_fallback_loop(
    stop_flag=None,
    green_seconds=12,
    all_red_seconds=2,
):
    """
    Fixed-time fallback if the adaptive algorithm/perception fails.

    Cycle: N -> E -> S -> W
    - Green phase uses traffic_signal.controller.run_signal() (includes a 3s yellow).
    - After each yellow, an explicit ALL_RED gap is inserted.
    """
    green_seconds = int(max(1, green_seconds))
    all_red_seconds = int(max(0, all_red_seconds))

    cycle_count = int(traffic_state.get("cycle", 0) or 0)
    sequence = ["N", "E", "S", "W"]
    idx = 0

    def on_signal_tick(phase, remaining):
        traffic_state["current_green"] = phase
        traffic_state["remaining_time"] = int(max(0, remaining))

    print("\n*** FALLBACK: switching to FIXED-TIME control ***\n")
    traffic_state["mode"] = "FIXED_FALLBACK"

    while not (stop_flag and stop_flag.is_set()):
        manual = traffic_state.get("manual_override", {})
        if manual.get("enabled") and manual.get("direction") in {"N", "S", "E", "W"}:
            selected_dir = manual["direction"]
            green_time = int(manual.get("duration", green_seconds))
            green_time = max(5, min(green_time, 90))
            traffic_state["mode"] = "MANUAL"
            traffic_state["manual_override"]["enabled"] = False
        else:
            selected_dir = sequence[idx]
            green_time = green_seconds
            traffic_state["mode"] = "FIXED_FALLBACK"
            idx = (idx + 1) % len(sequence)

        traffic_state["current_green"] = selected_dir
        traffic_state["remaining_time"] = green_time
        traffic_state["cycle"] = cycle_count

        run_signal(selected_dir, green_time, on_tick=on_signal_tick, stop_flag=stop_flag)

        # All-red clearance interval between phases.
        for remaining in range(all_red_seconds, 0, -1):
            if stop_flag and stop_flag.is_set():
                return
            on_signal_tick("ALL_RED", remaining)
            time.sleep(1)

        cycle_count += 1


def main_loop(stop_flag=None):
    cycle_count = 0

    sense_lock = threading.Lock()
    # Counts used by algorithm (sampled every 3 seconds).
    latest_vehicle_counts = {"N": 0, "S": 0, "E": 0, "W": 0}
    # Live counts for dashboard (updated every 1 second).
    latest_live_vehicle_counts = {"N": 0, "S": 0, "E": 0, "W": 0}
    latest_emergency_flags = {"N": False, "S": False, "E": False, "W": False}
    # Perception loop target rate. Higher means faster simulation and quicker violation detection.
    # It's "best effort": if YOLO is slow, the loop will run as fast as it can.
    perception_hz = 10.0
    perception_interval_seconds = 1.0 / max(1.0, perception_hz)
    sample_interval_seconds = 3
    algorithm_failed = threading.Event()
    started_at = time.time()

    def sensing_loop():
        # Continuously refresh counts/flags so phase switching isn't blocked by perception.
        last_sample = 0.0
        try:
            while not (stop_flag and stop_flag.is_set()) and not algorithm_failed.is_set():
                loop_t0 = time.perf_counter()
                vehicle_counts = {}
                emergency_flags = {}

                for direction, cap in videos.items():
                    ret, frame = cap.read()
                    if not ret:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()
                    if not ret or frame is None:
                        vehicle_counts[direction] = 0
                        emergency_flags[direction] = False
                        continue

                    detections = detect_vehicles(frame)
                    tracks = track_objects(detections, frame, camera_key=direction)
                    roi_tracks = filter_tracks_by_roi(tracks, lane_rois.get(direction))

                    # Count only inbound/opposite lane (lane2) for density, per your requirement:
                    # lane1 (red arrow direction) should not be counted.
                    lanes = lane_regions.get(direction) or {}
                    counted_tracks = roi_tracks
                    if "lane2" in lanes:
                        lane2_tracks = []
                        for t in roi_tracks:
                            ln = lane_for_track_bottom_center(t, frame.shape, lanes)
                            if ln == "lane2":
                                lane2_tracks.append(t)
                        counted_tracks = lane2_tracks

                    # Violation detection:
                    # If polygons are configured (>=2 lanes), use polygon lane-change only.
                    # The line-crossing fallback can create false positives when polygons exist.
                    if len(lanes) >= 2:
                        violations = check_lane_change_violations(
                            tracks=roi_tracks,
                            frame=frame,
                            direction=direction,
                            lane_regions=lane_regions,
                        )
                    else:
                        violations = check_lane_crossing(
                            tracks=tracks,
                            frame=frame,
                            direction=direction,
                        )
                    if len(violations) > 0:
                        print(f"Warning: {len(violations)} lane crossing(s) detected in {direction}")

                    vehicle_counts[direction] = len(counted_tracks)
                    emergency_flags[direction] = detect_emergency(counted_tracks)

                with sense_lock:
                    latest_live_vehicle_counts.update(vehicle_counts)
                    latest_emergency_flags.update(emergency_flags)

                    # Publish live perception to dashboard continuously.
                    # Without this, the dashboard only updates counts once per signal cycle.
                    now = time.time()
                    traffic_state["emergency"] = dict(latest_emergency_flags)
                    traffic_state["live_vehicle_count"] = dict(latest_live_vehicle_counts)
                    traffic_state["last_live_update"] = now

                    if now - last_sample >= sample_interval_seconds:
                        latest_vehicle_counts.update(latest_live_vehicle_counts)
                        traffic_state["vehicle_count"] = dict(latest_vehicle_counts)
                        last_sample = now

                # Throttle perception so we advance videos reasonably fast without pegging CPU.
                loop_dt = time.perf_counter() - loop_t0
                sleep_for = perception_interval_seconds - loop_dt
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except Exception:
            print("\n*** Perception thread failed; enabling fixed-time fallback ***")
            print(traceback.format_exc())
            traffic_state["fallback_reason"] = "perception_exception"
            algorithm_failed.set()

    threading.Thread(target=sensing_loop, daemon=True).start()

    def on_signal_tick(phase, remaining):
        traffic_state["current_green"] = phase
        traffic_state["remaining_time"] = int(max(0, remaining))

    while not (stop_flag and stop_flag.is_set()):
        if algorithm_failed.is_set():
            break

        # Watchdog: if perception stops updating, fall back to fixed-time control.
        last_live = float(traffic_state.get("last_live_update") or 0.0)
        now = time.time()
        if now - started_at > 10 and now - last_live > 10:
            traffic_state["fallback_reason"] = "perception_stalled"
            algorithm_failed.set()
            break

        # Snapshot latest perception (updated in background thread).
        with sense_lock:
            vehicle_counts = dict(latest_vehicle_counts)
            emergency_flags = dict(latest_emergency_flags)

        try:
            # 2) Update rolling traffic buffer.
            update_buffer(vehicle_counts)
            avg_density = get_average_density()

            # 3) Compute weighted priorities.
            priorities = {}
            for direction in avg_density:
                priorities[direction] = calculate_priority(
                    avg_density[direction],
                    waiting_time[direction],
                    int(bool(emergency_flags[direction])),
                    lane_importance[direction],
                )

            # 4) Select next green direction.
            manual = traffic_state.get("manual_override", {})
            if manual.get("enabled") and manual.get("direction") in {"N", "S", "E", "W"}:
                selected_dir = manual["direction"]
                green_time = int(manual.get("duration", 20))
                green_time = max(5, min(green_time, 90))
                traffic_state["mode"] = "MANUAL"
                traffic_state["manual_override"]["enabled"] = False
            elif True in emergency_flags.values():
                selected_dir = max(
                    emergency_flags.keys(),
                    key=lambda d: (int(bool(emergency_flags[d])), priorities[d]),
                )
                green_time = 40
                traffic_state["mode"] = "EMERGENCY"
            else:
                selected_dir = max(priorities, key=priorities.get)
                gmin = dynamic_gmin(avg_density[selected_dir])
                green_time = calculate_green_time(gmin, avg_density[selected_dir])
                traffic_state["mode"] = "AUTO"

            # 5) Publish state for dashboard.
            traffic_state["vehicle_count"] = vehicle_counts
            traffic_state["priority"] = priorities
            traffic_state["emergency"] = emergency_flags
            traffic_state["current_green"] = selected_dir
            traffic_state["remaining_time"] = green_time
            traffic_state["cycle"] = cycle_count

            # 6) Apply signal and update waiting time.
            run_signal(selected_dir, green_time, on_tick=on_signal_tick, stop_flag=stop_flag)

            cycle_duration = green_time + 3
            for direction in waiting_time:
                if direction == selected_dir:
                    waiting_time[direction] = 0
                else:
                    waiting_time[direction] += cycle_duration

            cycle_count += 1
        except Exception:
            print("\n*** Adaptive control failed; enabling fixed-time fallback ***")
            print(traceback.format_exc())
            traffic_state["fallback_reason"] = "algorithm_exception"
            algorithm_failed.set()
            break

    if not (stop_flag and stop_flag.is_set()) and algorithm_failed.is_set():
        fixed_time_fallback_loop(stop_flag=stop_flag)


if __name__ == "__main__":
    main_loop()
