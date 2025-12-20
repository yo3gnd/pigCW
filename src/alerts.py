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
        self.last_fit = None

    def on_alert(self, cb):
        self.cb = cb

    def add(self, t_ms, d_ms):
        self.items.append((t_ms, d_ms))

    def trim(self, now_ms):
        while self.items and now_ms - self.items[0][0] > self.max_window_ms:
            self.items.pop(0)

    def win_ms(self):
        if len(self.items) < 2:
            return 0

        return self.items[-1][0] - self.items[0][0]

    def med(self, xs):
        ys = sorted(xs)
        n = len(ys)
        if n < 1:
            return 0
        if n % 2:
            return ys[n // 2]
        i = n // 2
        return (ys[i - 1] + ys[i]) / 2.0

    def cv(self, xs):
        if len(xs) < 2:
            return 0.0

        m = sum(xs) / float(len(xs))
        if m <= 0:
            return 999.0

        v = 0.0
        for x in xs:
            v += (x - m) * (x - m)

        v = v / float(len(xs))
        return math.sqrt(v) / m

    def fit(self):
        ds = sorted(d for _, d in self.items if d > 0)
        n = len(ds)

        if n < self.min_marks:
            return None

        best = None
        for i in range(1, n):
            a = ds[:i]
            b = ds[i:]

            sa = len(a) / float(n)
            sb = len(b) / float(n)

            if sa < self.smin or sa > self.smax:
                continue
            if sb < self.lmin or sb > self.lmax:
                continue

            ma = self.med(a)
            mb = self.med(b)
            if ma < 1 or mb < 1:
                continue

            r = mb / float(ma)
            if r < self.rmin or r > self.rmax:
                continue

            ca = self.cv(a)
            cb = self.cv(b)
            if ca > self.cvmax or cb > self.cvmax:
                continue

            sc = abs(r - 3.0) + ca + cb
            z = {
                "marks": n,
                "short_marks": len(a),
                "long_marks": len(b),
                "short_ms": int(round(ma)),
                "long_ms": int(round(mb)),
                "ratio": round(r, 3),
                "short_share": round(sa, 3),
                "long_share": round(sb, 3),
                "short_cv": round(ca, 3),
                "long_cv": round(cb, 3),
                "score": round(sc, 4),
            }

            if best is None or z["score"] < best["score"]:
                best = z

        return best

    def run(self, now_ms):
        self.trim(now_ms)
        if not self.c.alerts_enable:
            return None

        if len(self.items) < self.min_marks:
            return None

        if self.win_ms() < self.min_window_ms:
            return None

        z = self.fit()
        self.last_fit = z

        if z:
            L.debug("cw fit %s", z)

        return None
