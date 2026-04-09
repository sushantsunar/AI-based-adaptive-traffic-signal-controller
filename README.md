# Final Year Project - Adaptive Traffic Signal + Violation Detection

This project simulates a 4-way intersection using 4 video feeds (`videos/north.mp4`, `south.mp4`, `east.mp4`, `west.mp4`), detects and tracks vehicles (YOLOv8 + DeepSORT), computes an adaptive green phase using a weighted priority algorithm (WAPS), and logs wrong-way/lane-crossing violations (SQLite + saved evidence images). A Flask dashboard shows live video streams and system state, and allows manual switching.

## Quick start

1) Create/activate a Python environment (recommended: Python 3.12).
2) Install dependencies (typical):
   - `pip install ultralytics opencv-python flask flask-cors deep-sort-realtime numpy`
3) Run everything (algorithm + dashboard):
   - `python runall.py`
4) Open the dashboard:
   - `http://127.0.0.1:5000/`

## What it runs

- Main control loop: `main.py` (vehicle counting, emergency detection, WAPS scheduling, signal timing)
- Dashboard server: `dashboard/app.py` (UI, JSON APIs, video streaming, violations viewer)
- Combined runner: `runall.py` (starts both)

## Data outputs

- SQLite DB: `database/traffic.db`
- Evidence images: `violations/` (paths stored as `violations/<filename>.jpg` in the DB)

## Configuration (ROI + lanes)

- ROI polygon (which part of each camera frame is “road”): `config/lane_rois.json`
  - Tool: `python define_lane_roi.py --direction N --source videos/north.mp4`
- Lane polygons (lane1/lane2 per direction; used for lane-change based wrong-way detection and for “count lane2 only” logic): `config/lane_regions.json`
  - Tool: `python define_lane_regions.py --direction N --source videos/north.mp4`
- Fallback divider line (used only when lane polygons are not configured): `config/lane_crossing_lines.json`

## Full documentation

See `docs/SYSTEM_DOCUMENTATION.md`.
For a focused “how it works” runtime flow, see `docs/SYSTEM_WORKFLOW.md`.
For AI diagram generators, use `docs/DIAGRAM_TEXT_SPEC.md`.
Generated Mermaid diagrams are in `docs/DIAGRAMS.md`.
For a very detailed beginner-friendly explanation, see `docs/SYSTEM_EXPLAINED.md`.
