import time

last_cycle = time.time()

def cycle_end():
    global last_cycle
    if time.time() - last_cycle > 10:
        last_cycle = time.time()
        return True
    return False
