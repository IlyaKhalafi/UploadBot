"""Monotonic transfer progress with average speed and estimated time remaining."""

import time


def human_size(size: float) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


class ProgressMeter:
    def __init__(self):
        self.started = self.last_update = time.monotonic()
        self.sent = 0

    def update(self, sent: int, total: int) -> str | None:
        self.sent = max(self.sent, sent)
        now = time.monotonic()
        if now - self.last_update < 4:
            return None
        self.last_update = now
        speed = self.sent / max(now - self.started, 0.001)
        seconds = max(0, total - self.sent) / speed if speed else 0
        eta = f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"
        return (
            f"Streaming… {self.sent / max(total, 1):.0%}\n"
            f"{human_size(self.sent)} / {human_size(total)} · {human_size(speed)}/s · ETA {eta}"
        )
