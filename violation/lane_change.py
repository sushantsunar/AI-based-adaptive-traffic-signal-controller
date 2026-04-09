import time
from datetime import datetime
from pathlib import Path

import cv2

from database.db import insert_lane_change_violation
from utils.lane_regions import load_lane_regions, lane_for_track_bottom_center


# Always write evidence to project-root/violations (not cwd/violations).
_BASE_DIR = Path(__file__).resolve().parents[1]
VIOLATIONS_DIR = _BASE_DIR / "violations"
VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Parameters (tune as needed)
# -----------------------------
COOLDOWN_SECONDS = 10
MIN_PREV_LANE_FRAMES = 3          # must be in lane2 for >= this many consecutive frames before switching
MIN_NEW_LANE_FRAMES = 2           # must be in lane1 for >= this many consecutive frames after switching
MIN_MOVE_PX = 6.0                 # ignore tiny point jitter
MIN_BBOX_AREA_PX = 28 * 28        # ignore very small/far vehicles (reduces false positives)


# -----------------------------
# Per-vehicle state
# -----------------------------
# vehicle_id -> (lane_name, consecutive_count)
_lane_streak = {}
# vehicle_id -> pending transition dict:
#   {from_lane, to_lane, from_cnt, to_cnt}
_pending_change = {}
# vehicle_id -> (x, y) last bottom-center point
_prev_point = {}
# vehicle_id -> epoch seconds (cooldown)
_last_violation_ts = {}


def reset_state():
    _lane_streak.clear()
    _pending_change.clear()
    _prev_point.clear()
    _last_violation_ts.clear()


def _bbox_area(track):
    x1, y1, x2, y2 = map(int, track.to_ltrb())
    w = max(0, x2 - x1)
    h = max(0, y2 - y1)
    return w * h


def check_lane_change_violations(tracks, frame, direction, lane_regions=None):
    """
    Wrong-way violation algorithm (your brief):

    - Assign each vehicle to lane based on bottom-center point inside lane polygons.
    - Maintain consecutive dwell/streak in the current lane.
    - When a transition occurs, start a pending change (from_lane -> to_lane).
    - Confirm violation only when:
        1) from_lane == lane2 and to_lane == lane1
        2) vehicle stayed in lane2 for MIN_PREV_LANE_FRAMES before switching
        3) vehicle stays in lane1 for MIN_NEW_LANE_FRAMES after switching
        4) point moved at least MIN_MOVE_PX (noise suppression)
        5) cooldown per vehicle
    - On violation: save FULL frame evidence (annotated) + insert DB row.

    Returns list of events:
      {vehicle_id, from_lane, to_lane, timestamp, image_path}
    """
    if frame is None:
        return []

    if lane_regions is None:
        lane_regions = load_lane_regions()

    direction = str(direction).upper()
    lanes = lane_regions.get(direction) or {}
    if len(lanes) < 2:
        return []

    h, w = frame.shape[:2]
    now = time.time()
    events = []

    for trk in tracks:
        if not trk.is_confirmed():
            continue

        vehicle_id = trk.track_id

        # Filter out tiny/far boxes: they jitter a lot and cause false lane flips.
        if _bbox_area(trk) < MIN_BBOX_AREA_PX:
            _pending_change.pop(vehicle_id, None)
            continue

        # Lane assignment point: bottom-center of bbox.
        lane_now = lane_for_track_bottom_center(trk, frame.shape, lanes)
        if lane_now is None:
            _pending_change.pop(vehicle_id, None)
            continue

        x1, y1, x2, y2 = map(int, trk.to_ltrb())
        cx = (x1 + x2) // 2
        cy = y2 - 1
        cx = max(0, min(w - 1, cx))
        cy = max(0, min(h - 1, cy))

        # Movement filter (noise suppression).
        prev_pt = _prev_point.get(vehicle_id)
        _prev_point[vehicle_id] = (cx, cy)
        if prev_pt is None:
            continue
        move = ((cx - prev_pt[0]) ** 2 + (cy - prev_pt[1]) ** 2) ** 0.5

        # Update lane streak (dwell in current lane).
        streak_lane, streak_cnt = _lane_streak.get(vehicle_id, (None, 0))
        if streak_lane is None:
            _lane_streak[vehicle_id] = (lane_now, 1)
            _pending_change.pop(vehicle_id, None)
            continue

        if lane_now == streak_lane:
            _lane_streak[vehicle_id] = (streak_lane, int(streak_cnt) + 1)
        else:
            # Transition observed: start pending change.
            _pending_change[vehicle_id] = {
                "from_lane": streak_lane,
                "to_lane": lane_now,
                "from_cnt": int(streak_cnt),
                "to_cnt": 1,
            }
            _lane_streak[vehicle_id] = (lane_now, 1)
            continue

        pend = _pending_change.get(vehicle_id)
        if not pend:
            continue
        if pend.get("to_lane") != lane_now:
            # Landed in a different lane than the pending target.
            _pending_change.pop(vehicle_id, None)
            continue

        pend["to_cnt"] = int(pend.get("to_cnt", 0)) + 1
        if int(pend["to_cnt"]) < MIN_NEW_LANE_FRAMES:
            continue

        # Cooldown.
        last_ts = _last_violation_ts.get(vehicle_id, 0)
        if now - last_ts < COOLDOWN_SECONDS:
            _pending_change.pop(vehicle_id, None)
            continue

        from_lane = str(pend.get("from_lane"))
        to_lane = str(pend.get("to_lane"))
        from_cnt = int(pend.get("from_cnt") or 0)

        # Violation rule: lane2 is incoming and lane1 is outgoing.
        # Vehicles crossing between these two opposing lanes are wrong-way.
        if not ((from_lane == "lane2" and to_lane == "lane1") or (from_lane == "lane1" and to_lane == "lane2")):
            _pending_change.pop(vehicle_id, None)
            continue

        # Must have dwelled in the origin lane before switching.
        if from_cnt < MIN_PREV_LANE_FRAMES:
            _pending_change.pop(vehicle_id, None)
            continue

        # Ignore tiny jitter near divider.
        if move < MIN_MOVE_PX:
            _pending_change.pop(vehicle_id, None)
            continue

        # Violation confirmed: save FULL frame evidence (annotated).
        timestamp_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp_file = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"vehicle_{vehicle_id}_{timestamp_file}.jpg"
        out_path_fs = str(VIOLATIONS_DIR / filename)
        image_path_db = f"violations/{filename}"

        evidence = frame.copy()
        cv2.rectangle(evidence, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(
            evidence,
            "Lane Violation",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imwrite(out_path_fs, evidence)

        insert_lane_change_violation(
            vehicle_id=vehicle_id,
            direction=direction,
            from_lane=from_lane,
            to_lane=to_lane,
            timestamp=timestamp_db,
            image_path=image_path_db,
        )

        events.append(
            {
                "vehicle_id": vehicle_id,
                "from_lane": from_lane,
                "to_lane": to_lane,
                "timestamp": timestamp_db,
                "image_path": image_path_db,
            }
        )

        _last_violation_ts[vehicle_id] = now
        _pending_change.pop(vehicle_id, None)

    return events

