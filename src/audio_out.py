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
        self.tx_hz = int(hz)

    def set_rx_hz(self, hz):
        self.rx_hz = int(hz)

    def set_tx(self, on):
        self.tx_on = 1 if on else 0

    def set_rx(self, on):
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
            blocksize=0,
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

        out = np.zeros(frames, dtype="float32")

        for i in range(frames):
            if tx_g < tx_t:
                tx_g += self.fade_k
                if tx_g > tx_t:
                    tx_g = tx_t
            elif tx_g > tx_t:
                tx_g -= self.fade_k
                if tx_g < tx_t:
                    tx_g = tx_t

            if rx_g < rx_t:
                rx_g += self.fade_k
                if rx_g > rx_t:
                    rx_g = rx_t
            elif rx_g > rx_t:
                rx_g -= self.fade_k
                if rx_g < rx_t:
                    rx_g = rx_t

            y = 0.0

            if tx_g > 0.0:
                y += math.sin(tx_p) * tx_g * a_tx
                tx_p += tx_k
                if tx_p >= self.pi2:
                    tx_p -= self.pi2

            if rx_g > 0.0:
                y += math.sin(rx_p) * rx_g * a_rx
                rx_p += rx_k
                if rx_p >= self.pi2:
                    rx_p -= self.pi2

            out[i] = y

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
        if not self.stream:
            return

        self.stream.stop()
        self.stream.close()
        self.stream = None
