import json
from pathlib import Path


DEFAULT_ROI_PATH = Path("config/lane_rois.json")


def load_lane_rois(config_path=DEFAULT_ROI_PATH):
    """
    Load per-direction lane polygons from JSON.

    JSON shape:
    {
      "N": [[x1, y1], [x2, y2], ...],
      "S": [[...]],
      "E": [[...]],
      "W": [[...]]
    }
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rois = {}
    for direction, points in data.items():
        if not isinstance(points, list) or len(points) < 3:
            continue
        valid_points = []
        for pt in points:
            if not isinstance(pt, list) or len(pt) != 2:
                continue
            x, y = int(pt[0]), int(pt[1])
            valid_points.append((x, y))
        if len(valid_points) >= 3:
            rois[direction] = valid_points
    return rois


def _point_in_polygon(px, py, polygon):
    # Ray-casting point-in-polygon test.
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


def filter_tracks_by_roi(tracks, polygon):
    """
    Keep only confirmed tracks whose bbox center lies inside the ROI polygon.
    """
    if not polygon:
        return tracks

    filtered = []
    for track in tracks:
        if not track.is_confirmed():
            continue
        x1, y1, x2, y2 = map(int, track.to_ltrb())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        if _point_in_polygon(cx, cy, polygon):
            filtered.append(track)
    return filtered
