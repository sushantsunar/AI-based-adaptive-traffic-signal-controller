import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="Define multiple lane polygons per camera direction.")
    p.add_argument("--source", default="videos/north.mp4", help="Video path")
    p.add_argument("--direction", required=True, choices=["N", "S", "E", "W"], help="Camera direction key")
    p.add_argument("--config", default="config/lane_regions.json", help="Lane regions JSON path")
    return p.parse_args()


def load_config(path):
    p = Path(path)
    if not p.exists():
        return {"N": {}, "S": {}, "E": {}, "W": {}}
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    for d in ["N", "S", "E", "W"]:
        data.setdefault(d, {})
        if not isinstance(data[d], dict):
            data[d] = {}
    return data


def save_config(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    args = parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.source}")

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError("Could not read first frame from source video.")

    config = load_config(args.config)
    direction = args.direction

    lane_name = None
    points = []

    window = f"Define Lanes - {direction}"

    def on_mouse(event, x, y, flags, param):
        nonlocal points
        if event == cv2.EVENT_LBUTTONDOWN and lane_name:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    print("Instructions:")
    print("- Type lane name in console when prompted (e.g. lane1, lane2)")
    print("- Left click: add polygon point (only after lane name set)")
    print("- Right click: undo last point")
    print("- c: clear points for current lane")
    print("- s: save current lane polygon")
    print("- q: quit")

    while True:
        if lane_name is None:
            lane_name = input(f"Enter lane name for direction {direction} (or blank to quit): ").strip()
            if not lane_name:
                break
            points = []

        canvas = frame.copy()

        # Draw existing lanes
        for existing_name, poly in config.get(direction, {}).items():
            pts = [(int(x), int(y)) for x, y in poly]
            if len(pts) >= 3:
                arr = np.array(pts, dtype=np.int32)
                cv2.polylines(canvas, [arr], True, (0, 150, 200), 2)
                x0, y0 = pts[0]
                cv2.putText(canvas, existing_name, (x0, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 150, 200), 2)

        # Draw current lane being edited
        for i, (x, y) in enumerate(points):
            cv2.circle(canvas, (x, y), 5, (0, 255, 255), -1)
            cv2.putText(canvas, str(i + 1), (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        if len(points) >= 2:
            for i in range(len(points) - 1):
                cv2.line(canvas, points[i], points[i + 1], (0, 255, 0), 2)
        if len(points) >= 3:
            cv2.line(canvas, points[-1], points[0], (0, 255, 0), 2)

        cv2.putText(
            canvas,
            f"Editing: {lane_name} | Points: {len(points)}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.imshow(window, canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord("c"):
            points = []
        elif key == ord("q"):
            break
        elif key == ord("s"):
            if len(points) < 3:
                print("Need at least 3 points to save a lane polygon.")
                continue
            config[direction][lane_name] = [[int(x), int(y)] for x, y in points]
            save_config(args.config, config)
            print(f"Saved lane '{lane_name}' for {direction} in {args.config}")
            lane_name = None

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
