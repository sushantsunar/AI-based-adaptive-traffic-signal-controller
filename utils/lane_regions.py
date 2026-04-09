import json
from pathlib import Path


DEFAULT_LANE_REGIONS_PATH = Path("config/lane_regions.json")

def point_in_polygon(px, py, polygon):
    # Ray casting
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def lane_for_point(x, y, lanes):
    """
    lanes: {lane_name: [(x,y), ...], ...}
    """
    for lane_name, polygon in (lanes or {}).items():
        if point_in_polygon(int(x), int(y), polygon):
            return lane_name
    return None


def lane_for_track_bottom_center(track, frame_shape, lanes):
    """
    Stable lane assignment for road videos: use bottom-center of bbox.
    Returns lane_name or None.
    """
    if track is None or frame_shape is None:
        return None
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = map(int, track.to_ltrb())
    cx = (x1 + x2) // 2
    cy = y2 - 1
    cx = max(0, min(w - 1, cx))
    cy = max(0, min(h - 1, cy))
    return lane_for_point(cx, cy, lanes)


def load_lane_regions(config_path=DEFAULT_LANE_REGIONS_PATH):
    """
    Load per-direction lane polygons from JSON.

    JSON shape:
    {
      "N": { "lane1": [[x,y], ...], "lane2": [[x,y], ...] },
      "S": { ... },
      "E": { ... },
      "W": { ... }
    }
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    regions = {}
    for direction, lanes in data.items():
        if not isinstance(lanes, dict):
            continue
        clean = {}
        for lane_name, points in lanes.items():
            if not isinstance(points, list) or len(points) < 3:
                continue
            pts = []
            for pt in points:
                if not isinstance(pt, list) or len(pt) != 2:
                    continue
                pts.append((int(pt[0]), int(pt[1])))
            if len(pts) >= 3:
                clean[str(lane_name)] = pts
        if clean:
            regions[str(direction).upper()] = clean
    return regions
