import logging, math

import numpy as np


L = logging.getLogger(__name__)

a_tx = 0.35
a_rx = 0.35


class AudioSide:
    def __init__(self, m, k):
        self.m = m
        self.k = k

    def set_frequency(self, hz):
        if self.k == "tx":
            self.m.set_tx_hz(hz)
        else:
            self.m.set_rx_hz(hz)

    def set_enabled(self, on):
        if self.k == "tx":
            self.m.set_tx(on)
        else:
            self.m.set_rx(on)


class AudioToneMix:
    def __init__(self, c):
        self.c = c

        self.sd = None
        self.stream = None

        self.tx_hz = int(c.tx_tone_hz)
        self.rx_hz = int(c.rx_tone_hz)

        self.tx_on = 0
        self.rx_on = 0

        self.tx_g = 0.0
        self.rx_g = 0.0

        self.tx_p = 0.0
        self.rx_p = 0.0

        self.pi2 = math.pi * 2.0

        self.fade_n = int((c.audio_fade_ms / 1000.0) * c.audio_samplerate)
        if self.fade_n < 1:
            self.fade_n = 1

        self.fade_k = 1.0 / self.fade_n

        self.status_n = 0
        self.status_s = ""

        self.tx = AudioSide(self, "tx")
        self.rx = AudioSide(self, "rx")

        self.start()

    def set_tx_hz(self, hz):
        self.log_status()
        self.tx_hz = int(hz)

    def set_rx_hz(self, hz):
        self.log_status()
        self.rx_hz = int(hz)

    def set_tx(self, on):
        self.log_status()
        self.tx_on = 1 if on else 0

    def set_rx(self, on):
        self.log_status()
        self.rx_on = 1 if on else 0

    def start(self):
        if not self.c.audio_enable:
            return

        import sounddevice as sd

        self.sd = sd

        d = None
        if self.c.audio_device != "default":
            d = self.c.audio_device

        self.stream = sd.OutputStream(
            samplerate=self.c.audio_samplerate,
            channels=1,
            dtype="float32",
            latency=self.c.audio_latency,
            blocksize=896,
            device=d,
            callback=self.cb,
        )

        self.stream.start()

        L.info(
            "audio start %s %s %s %s",
            self.c.audio_device,
            self.c.audio_samplerate,
            self.c.audio_latency,
            self.stream.latency,
        )

    def cb(self, outdata, frames, tm, st):
        if st:
            self.status_n += 1
            self.status_s = str(st)

        tx_p = self.tx_p
        rx_p = self.rx_p
        tx_g = self.tx_g
        rx_g = self.rx_g

        tx_k = self.pi2 * self.tx_hz / self.c.audio_samplerate
        rx_k = self.pi2 * self.rx_hz / self.c.audio_samplerate

        tx_t = 1.0 if self.tx_on else 0.0
        rx_t = 1.0 if self.rx_on else 0.0

        x = np.arange(frames, dtype="float32")
        r = x + 1.0
        out = np.zeros(frames, dtype="float32")

        if tx_g == tx_t:
            tx_v = tx_g
            tx_g = tx_v
        elif tx_g < tx_t:
            tx_v = tx_g + (self.fade_k * r)
            tx_v = np.minimum(tx_v, tx_t)
            tx_g = float(tx_v[-1])
        else:
            tx_v = tx_g - (self.fade_k * r)
            tx_v = np.maximum(tx_v, tx_t)
            tx_g = float(tx_v[-1])

        if rx_g == rx_t:
            rx_v = rx_g
            rx_g = rx_v
        elif rx_g < rx_t:
            rx_v = rx_g + (self.fade_k * r)
            rx_v = np.minimum(rx_v, rx_t)
            rx_g = float(rx_v[-1])
        else:
            rx_v = rx_g - (self.fade_k * r)
            rx_v = np.maximum(rx_v, rx_t)
            rx_g = float(rx_v[-1])

        if tx_g > 0.0 or tx_t > 0.0:
            p = tx_p + (tx_k * x)
            out += np.sin(p) * tx_v * a_tx
            tx_p = (tx_p + (tx_k * frames)) % self.pi2

        if rx_g > 0.0 or rx_t > 0.0:
            p = rx_p + (rx_k * x)
            out += np.sin(p) * rx_v * a_rx
            rx_p = (rx_p + (rx_k * frames)) % self.pi2

        self.tx_p = tx_p
        self.rx_p = rx_p
        self.tx_g = tx_g
        self.rx_g = rx_g

        outdata[:, 0] = out

    def log_status(self):
        if not self.status_n:
            return

        L.warning("audio status %s %s", self.status_n, self.status_s)
        self.status_n = 0
        self.status_s = ""

    def stop(self):
        self.log_status()

        if not self.stream:
            return

        self.stream.stop()
        self.stream.close()
        self.stream = None
