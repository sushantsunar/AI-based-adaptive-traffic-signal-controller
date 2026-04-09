
import cv2
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from database.db import insert_violation

# Always write evidence to project-root/violations (not cwd/violations).
_BASE_DIR = Path(__file__).resolve().parents[1]
VIOLATION_DIR = _BASE_DIR / "violations"
VIOLATION_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = _BASE_DIR / "config" / "lane_crossing_lines.json"

# Noise suppression + duplicate control
MIN_MOVE_PX = 8.0
MIN_DISTANCE_TO_LINE_PX = 5.0
COOLDOWN_SECONDS = 8
MIN_PREV_SIDE_FRAMES = 3
MIN_NEW_SIDE_FRAMES = 2
MIN_BBOX_AREA_PX = 28 * 28

# vehicle_id -> (cx, cy, side_value)
previous_positions = {}
# vehicle_id -> (side_sign, count)
side_streak = {}
# vehicle_id -> pending crossing dict
pending_cross = {}
# vehicle_id -> epoch seconds
last_violation_ts = {}


def reset_state():
    previous_positions.clear()
    side_streak.clear()
    pending_cross.clear()
    last_violation_ts.clear()


def _load_lines_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


_LINES = _load_lines_config()


def _line_for_direction(direction):
    d = str(direction).upper()
    entry = _LINES.get(d)
    if not isinstance(entry, dict):
        # Fallback: old behavior using x=500 as a vertical line.
        return (500, 0), (500, 100)
    p1 = entry.get("p1")
    p2 = entry.get("p2")
    if (
        isinstance(p1, list)
        and isinstance(p2, list)
        and len(p1) == 2
        and len(p2) == 2
    ):
        return (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1]))
    return (500, 0), (500, 100)


def _side_value(point, p1, p2):
    # Cross product sign indicates which side of the directed line the point is on.
    x, y = point
    x1, y1 = p1
    x2, y2 = p2
    return (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)


def _distance_to_line_px(side_val, p1, p2):
    x1, y1 = p1
    x2, y2 = p2
    denom = math.hypot(x2 - x1, y2 - y1)
    if denom <= 1e-6:
        return 0.0
    return abs(side_val) / denom


def _bbox_area(track):
    x1, y1, x2, y2 = map(int, track.to_ltrb())
    w = max(0, x2 - x1)
    h = max(0, y2 - y1)
    return w * h

# ===============================
# MAIN FUNCTION
# ===============================

def check_lane_crossing(tracks, frame, direction):
    """
    Detects lane crossing violations and saves frame evidence.

    Parameters:
    ----------
    tracks : list
        Output from DeepSORT tracker
    frame : numpy array
        Current video frame
    direction : str
        Camera direction (N, S, E, W)

    Returns:
    -------
    list
        List of detected violations (vehicle IDs)
    """

    violations = []
    p1, p2 = _line_for_direction(direction)
    now = time.time()
    h, w = frame.shape[:2] if frame is not None else (0, 0)

    # Determine which side corresponds to image-right vs image-left so we can treat
    # "right->left" as lane2->lane1 (wrong-way divider crossing).
    # Works for any non-degenerate line.
    right_probe = (max(0, w - 1), max(0, h // 2))
    left_probe = (0, max(0, h // 2))
    right_side = _side_value(right_probe, p1, p2)
    left_side = _side_value(left_probe, p1, p2)
    lane2_sign = 1 if right_side > 0 else (-1 if right_side < 0 else 0)
    lane1_sign = 1 if left_side > 0 else (-1 if left_side < 0 else 0)

    for track in tracks:

        # Skip unconfirmed tracks
        if not track.is_confirmed():
            continue

        track_id = track.track_id

        # Bounding box
        x1, y1, x2, y2 = map(int, track.to_ltrb())
        if _bbox_area(track) < MIN_BBOX_AREA_PX:
            pending_cross.pop(track_id, None)
            continue

        # Use bottom-center (more stable for road divider checks than bbox centroid).
        cx = int((x1 + x2) / 2)
        cy = int(y2 - 1)
        cx = max(0, min(w - 1, cx))
        cy = max(0, min(h - 1, cy))
        side = _side_value((cx, cy), p1, p2)
        side_sign = 1 if side > 0 else (-1 if side < 0 else 0)
        if side_sign == 0:
            # Exactly on the line; ignore.
            pending_cross.pop(track_id, None)
            continue

        # Maintain side streak for stability.
        last_sign, last_cnt = side_streak.get(track_id, (None, 0))
        if last_sign == side_sign:
            side_streak[track_id] = (side_sign, int(last_cnt) + 1)
        else:
            # Sign flipped (candidate crossing).
            if last_sign is not None:
                pending_cross[track_id] = {
                    "from_sign": last_sign,
                    "to_sign": side_sign,
                    "from_cnt": int(last_cnt),
                    "to_cnt": 1,
                }
            side_streak[track_id] = (side_sign, 1)

        # If vehicle seen before
        if track_id in previous_positions:

            prev_cx, prev_cy, prev_side = previous_positions[track_id]

            moved = math.hypot(cx - prev_cx, cy - prev_cy)
            dist_prev = _distance_to_line_px(prev_side, p1, p2)
            dist_now = _distance_to_line_px(side, p1, p2)

            pend = pending_cross.get(track_id)
            if pend and pend.get("to_sign") == side_sign:
                pend["to_cnt"] = int(pend.get("to_cnt", 0)) + 1

            # Confirm a real divider crossing:
            # - stable on previous side for some frames
            # - stable on new side for some frames
            # - far enough from the line (avoid flicker)
            # - moved enough
            # - crossing between the two opposing lanes (lane2 <-> lane1)
            crossed = False
            if pend:
                from_sign = int(pend.get("from_sign"))
                to_sign = int(pend.get("to_sign"))
                crossed = (
                    int(pend.get("from_cnt", 0)) >= MIN_PREV_SIDE_FRAMES
                    and int(pend.get("to_cnt", 0)) >= MIN_NEW_SIDE_FRAMES
                    and moved >= MIN_MOVE_PX
                    and dist_prev >= MIN_DISTANCE_TO_LINE_PX
                    and dist_now >= MIN_DISTANCE_TO_LINE_PX
                    and lane2_sign != 0
                    and lane1_sign != 0
                    and (
                        (from_sign == lane2_sign and to_sign == lane1_sign)
                        or (from_sign == lane1_sign and to_sign == lane2_sign)
                    )
                )

            if crossed:
                last_ts = last_violation_ts.get(track_id, 0)
                if now - last_ts < COOLDOWN_SECONDS:
                    previous_positions[track_id] = (cx, cy, side)
                    pending_cross.pop(track_id, None)
                    continue

                timestamp_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                timestamp_file = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

                filename = f"vehicle_{track_id}_{timestamp_file}.jpg"
                out_path_fs = str(VIOLATION_DIR / filename)
                # Store as a relative web-friendly path for the dashboard.
                image_path_db = f"violations/{filename}"

                # Save full frame evidence (annotated)
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

                insert_violation(
                    vehicle_id=track_id,
                    direction=direction,
                    timestamp=timestamp_db,
                    image_path=image_path_db,
                )

                last_violation_ts[track_id] = now
                pending_cross.pop(track_id, None)

                violations.append({
                    "vehicle_id": track_id,
                    "direction": direction,
                    "image_path": image_path_db,
                    "time": timestamp_db
                })

        # Update previous position
        previous_positions[track_id] = (cx, cy, side)

    return violations
