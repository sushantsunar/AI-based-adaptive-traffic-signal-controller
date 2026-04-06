"""
Detects emergency vehicles using object labels from tracking results.
If any emergency vehicle is found, it raises a flag.
"""

def detect_emergency(tracks):
    """
    Input  : Tracked objects from DeepSORT
    Output : True if emergency vehicle exists else False
    """

    for track in tracks:
        if not track.is_confirmed():
            continue

        label = track.get_det_class()
        if not label:
            continue
        norm = str(label).strip().lower().replace("-", " ").replace("_", " ")

        if (
            "ambulance" in norm
            or "police" in norm
            or "fire truck" in norm
            or "firetruck" in norm
        ):
            return True

    return False
