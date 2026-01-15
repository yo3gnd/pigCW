import json, logging, math, queue, subprocess, threading


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
        self.last_ev = None

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

    def mk_ev(self, now_ms, z):
        ev = {
            "event": "cw_activity",
            "source": self.c.alerts_source,
            "ts_ms": now_ms,
            "window_ms": self.win_ms(),
            "marks": z["marks"],
            "short_marks": z["short_marks"],
            "long_marks": z["long_marks"],
            "short_ms": z["short_ms"],
            "long_ms": z["long_ms"],
            "ratio": z["ratio"],
            "cooldown_s": self.cool_s,
        }

        return ev

    def run(self, now_ms):
        self.trim(now_ms)
        if not self.c.alerts_enable:
            return None

        if now_ms < self.cool_until_ms:
            return None

        if len(self.items) < self.min_marks:
            return None

        if self.win_ms() < self.min_window_ms:
            return None

        z = self.fit()
        self.last_fit = z

        if z:
            L.debug("cw fit %s", z)
            ev = self.mk_ev(now_ms, z)
            self.last_ev = ev
            # print("cw dbg", ev["marks"], ev["short_ms"], ev["long_ms"], ev["ratio"])
            self.cool_until_ms = now_ms + (self.cool_s * 1000)
            self.items = []

            if self.c.alerts_print:
                print("cw activity", ev["marks"], ev["short_ms"], ev["long_ms"], ev["ratio"])

            return ev

        return None


class AlertOut:
    def __init__(self, c):
        self.c = c
        self.q = queue.Queue()
        self.t = None
        self.run_yes = False
        self.mq = None

    def start(self):
        self.run_yes = True
        self.mqtt_start()
        self.t = threading.Thread(target=self.loop)
        self.t.start()

    def stop(self):
        self.run_yes = False
        self.q.put(None)
        if self.mq:
            self.mq.loop_stop()
            self.mq.disconnect()

    def put(self, ev):
        self.q.put(ev)

    def do_script(self, ev):
        if not self.c.alerts_script_enable:
            return
        if not self.c.alerts_script_path:
            return

        cmd = [self.c.alerts_script_path] + list(self.c.alerts_script_args)
        try:
            subprocess.run(
                cmd,
                input=json.dumps(ev),
                text=True,
                timeout=self.c.alerts_script_timeout_s,
                capture_output=True,
            )
        except Exception as e:
            L.warning("script fail %s", e)

    def mqtt_start(self):
        if not self.c.alerts_mqtt_enable:
            return

        try:
            import paho.mqtt.client as mqtt
        except Exception as e:
            L.warning("mqtt import %s", e)
            return

        try:
            self.mq = mqtt.Client(
                client_id=self.c.alerts_mqtt_client_id,
                protocol=mqtt.MQTTv311,
            )
            if self.c.alerts_mqtt_username:
                self.mq.username_pw_set(
                    self.c.alerts_mqtt_username,
                    self.c.alerts_mqtt_password,
                )

            self.mq.connect(
                self.c.alerts_mqtt_host,
                self.c.alerts_mqtt_port,
                self.c.alerts_mqtt_keepalive_s,
            )
            self.mq.loop_start()
        except Exception as e:
            self.mq = None
            L.warning("mqtt start %s", e)

    def fmt(self, s, ev):
        if not s:
            return json.dumps(ev)
        try:
            return s.format(**ev)
        except Exception:
            return s

    def do_mqtt(self, ev):
        if not self.mq:
            return

        try:
            self.mq.publish(
                self.c.alerts_mqtt_topic,
                self.fmt(self.c.alerts_mqtt_payload, ev),
                qos=self.c.alerts_mqtt_qos,
                retain=self.c.alerts_mqtt_retain,
            )
        except Exception as e:
            L.warning("mqtt send %s", e)

    def loop(self):
        while self.run_yes:
            try:
                ev = self.q.get(timeout=0.2)
            except queue.Empty:
                continue

            if ev is None:
                continue

            self.do_script(ev)
            self.do_mqtt(ev)
            if False:
                print("alert out", ev)
