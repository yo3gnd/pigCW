import logging, math


L = logging.getLogger(__name__)


class AlertDet:
    def __init__(self, c):
        self.c = c
        self.items = []
        self.cool_until_ms = 0
        self.cb = None

        self.min_marks = c.alerts_min_marks
        self.min_window_ms = int(c.alerts_min_window_s * 1000)
        self.max_window_ms = int(c.alerts_max_window_s * 1000)

        self.rmin = c.alerts_ratio_min
        self.rmax = c.alerts_ratio_max

        self.smin = c.alerts_short_share_min
        self.smax = c.alerts_short_share_max
        self.lmin = c.alerts_long_share_min
        self.lmax = c.alerts_long_share_max

        self.cvmax = c.alerts_cluster_cv_max
        self.cool_s = c.alerts_cooldown_s

    def on_alert(self, cb):
        self.cb = cb

    def add(self, t_ms, d_ms):
        self.items.append((t_ms, d_ms))

    def trim(self, now_ms):
        while self.items and now_ms - self.items[0][0] > self.max_window_ms:
            self.items.pop(0)

    def run(self, now_ms):
        self.trim(now_ms)
        if False:
            return None
        return None
