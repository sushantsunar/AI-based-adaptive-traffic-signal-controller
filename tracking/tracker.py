"""
This module ensures each vehicle is counted only once.
DeepSORT assigns a unique ID to each vehicle.
"""

from deep_sort_realtime.deepsort_tracker import DeepSort

_trackers = {}


def _get_tracker(camera_key):
    # DeepSORT expects a consistent stream. Using one global tracker for multiple videos
    # mixes identities across directions and breaks confirmation/ID stability.
    key = str(camera_key or "default").upper()
    trk = _trackers.get(key)
    if trk is None:
        trk = DeepSort(max_age=30)
        _trackers[key] = trk
    return trk

def track_objects(detections, frame, camera_key="default"):
    """
    Input  : YOLO detections + frame
    Output : Tracked vehicle objects
    """
    if frame is None:
        return []
    tracker = _get_tracker(camera_key)
    tracks = tracker.update_tracks(detections, frame=frame)
    return tracks


def reset_trackers(camera_key=None):
    """
    Reset DeepSORT state.
    Useful for demo seeks / video jumps where frame continuity is broken.
    """
    global _trackers
    if camera_key is None:
        _trackers = {}
        return
    key = str(camera_key or "default").upper()
    _trackers.pop(key, None)
