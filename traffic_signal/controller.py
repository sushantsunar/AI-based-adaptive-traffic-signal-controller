import time


def run_signal(direction, green_time, on_tick=None, stop_flag=None):
    green_time = int(max(1, green_time))
    print(f"\nGREEN {direction} for {green_time} seconds")

    for remaining in range(green_time, 0, -1):
        if stop_flag and stop_flag.is_set():
            return
        if on_tick:
            on_tick(direction, remaining)
        time.sleep(1)

    yellow_phase = f"YELLOW_{direction}"
    print("YELLOW for 3 seconds")
    for remaining in range(3, 0, -1):
        if stop_flag and stop_flag.is_set():
            return
        if on_tick:
            on_tick(yellow_phase, remaining)
        time.sleep(1)

    if on_tick:
        # End of yellow. Some time may be spent computing the next phase; the UI can treat
        # YELLOW_* at 0 seconds as "all red" to avoid an extra visible delay.
        on_tick(yellow_phase, 0)
