"""
This module detects vehicles from a single video frame using YOLOv8.
It returns bounding boxes that will later be tracked by DeepSORT.
"""

import os
from pathlib import Path
from ultralytics import YOLO

DEFAULT_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH")
if not DEFAULT_MODEL_PATH:
    project_root = Path(__file__).resolve().parents[1]
    best_path = project_root / "best.pt"
    DEFAULT_MODEL_PATH = str(best_path) if best_path.exists() else "yolov8n.pt"

# Load YOLO model (custom best.pt is preferred when available).
model = YOLO(DEFAULT_MODEL_PATH)

VEHICLE_CLASS_NAMES = {"ambulance", "bus", "car", "motorcycle", "truck"}
VEHICLE_CLASSES = [
    cls
    for cls, name in model.names.items()
    if str(name).strip().lower() in VEHICLE_CLASS_NAMES
]

if not VEHICLE_CLASSES:
    # Fallback to standard COCO vehicle IDs if model.names does not contain our vehicle labels.
    VEHICLE_CLASSES = [2, 3, 5, 7]

def detect_vehicles(frame):
    """
    Input  : Single video frame
    Output : List of detections [[bbox, confidence, class_name], ...] where bbox=[x,y,w,h]
    """

    # verbose=False prevents per-frame console spam and reduces overhead.
    results = model(frame, verbose=False)[0]
    detections = []

    for box in results.boxes:
        cls = int(box.cls[0])

        if cls in VEHICLE_CLASSES:
            x1, y1, x2, y2 = box.xyxy[0]
            w = x2 - x1
            h = y2 - y1
            conf = float(box.conf[0])
            class_name = model.names[cls]

            detections.append([[int(x1), int(y1), int(w), int(h)], conf, class_name])

    return detections
