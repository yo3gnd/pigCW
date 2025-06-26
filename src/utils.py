import time


def wall_clock_ms():
    return round(time.time() * 1000)


def mono_clock_ms():
    return round(time.monotonic() * 1000)
