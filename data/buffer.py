"""
Stores vehicle counts captured every 3 seconds.
Helps smooth sudden spikes and ensures stable decisions.
"""

from collections import deque

buffer = {
    "N": deque(maxlen=4),
    "S": deque(maxlen=4),
    "E": deque(maxlen=4),
    "W": deque(maxlen=4)
}

def update_buffer(counts):
    """
    Input : Vehicle count per direction
    Stores data in rolling buffer
    """
    for d in counts:
        buffer[d].append(counts[d])

def get_average_density():
    """
    Output : Smoothed vehicle density per direction
    """
    avg = {}
    for d in buffer:
        if len(buffer[d]) == 0:
            avg[d] = 0
        else:
            avg[d] = sum(buffer[d]) / len(buffer[d])
    return avg
