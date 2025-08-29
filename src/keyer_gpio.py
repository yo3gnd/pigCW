import logging, math, queue, threading, time

import pigpio

from .keyer_engine import KeyerEngine
from .utils import mono_clock_ms


L = logging.getLogger(__name__)
gpio = pigpio.pi()
wave_lock = threading.Lock()


class ToneMix:
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


class ToneMixerXor:
    def __init__(self, pin, tx_hz, rx_hz):
        self.pin = pin
        gpio.set_mode(self.pin, pigpio.OUTPUT)
        self.tx_hz = int(tx_hz)
        self.rx_hz = int(rx_hz)
        self.tx_on = 0
        self.rx_on = 0
        self.x = -1
        self.y = -1
        self.z = -1
        self.rebuild()
        self.tx = ToneMix(self, "tx")
        self.rx = ToneMix(self, "rx")

    def mk1(self, hz):
        u = int(1000000 / hz / 2)
        w = []
        w.append(pigpio.pulse(1 << self.pin, 0, u))
        w.append(pigpio.pulse(0, 1 << self.pin, u))

        gpio.wave_add_new()
        gpio.wave_add_generic(w)
        return gpio.wave_create()

    def mkx(self, a, b):
        ua = int(1000000 / a / 2)
        ub = int(1000000 / b / 2)
        r = (2 * ua * 2 * ub) // math.gcd(2 * ua, 2 * ub)

        sa = 1
        sb = 1
        so = sa ^ sb

        t = 0
        ta = ua
        tb = ub
        w = []

        while t < r:
            n = min(ta, tb)
            d = n - t

            if d > 0:
                if so:
                    w.append(pigpio.pulse(1 << self.pin, 0, d))
                else:
                    w.append(pigpio.pulse(0, 1 << self.pin, d))

            t = n

            if ta == n:
                sa ^= 1
                ta += ua

            if tb == n:
                sb ^= 1
                tb += ub

            so = sa ^ sb

        gpio.wave_add_new()
        gpio.wave_add_generic(w)
        return gpio.wave_create()

    def rebuild(self):
        a = self.x
        b = self.y
        c = self.z

        self.x = self.mk1(self.tx_hz)
        self.y = self.mkx(self.tx_hz, self.rx_hz)
        self.z = self.mk1(self.rx_hz)

        if a >= 0:
            gpio.wave_delete(a)
        if b >= 0:
            gpio.wave_delete(b)
        if c >= 0:
            gpio.wave_delete(c)

    def set_tx_hz(self, hz):
        hz = int(hz)
        if hz == self.tx_hz:
            return
        with wave_lock:
            self.tx_hz = hz
            self.rebuild()
            self.apply()

    def set_rx_hz(self, hz):
        hz = int(hz)
        if hz == self.rx_hz:
            return
        with wave_lock:
            self.rx_hz = hz
            self.rebuild()
            self.apply()

    def set_tx(self, on):
        with wave_lock:
            self.tx_on = 1 if on else 0
            self.apply()

    def set_rx(self, on):
        with wave_lock:
            self.rx_on = 1 if on else 0
            self.apply()

    def apply(self):
        if self.tx_on and self.rx_on:
            gpio.wave_send_repeat(self.y)
            return

        if self.tx_on:
            gpio.wave_send_repeat(self.x)
            return

        if self.rx_on:
            gpio.wave_send_repeat(self.z)
            return

        gpio.wave_tx_stop()
        gpio.write(self.pin, 0)

    def stop(self):
        with wave_lock:
            self.tx_on = 0
            self.rx_on = 0
            gpio.wave_tx_stop()
            gpio.write(self.pin, 0)

        if self.x >= 0:
            gpio.wave_delete(self.x)
        if self.y >= 0:
            gpio.wave_delete(self.y)
        if self.z >= 0:
            gpio.wave_delete(self.z)


class KeyerGPIO:
    def __init__(self, config, on_element, mix):
        self.config = config
        self.on_element = on_element

        self.event_queue = queue.Queue()
        self.tone_output = mix.tx
        self.session_start_ms = mono_clock_ms()
        self.eng = KeyerEngine(config, self.tone_output, on_element, gpio)

        self.dit_pin = config.GPIO_DIT
        self.dah_pin = config.GPIO_DAH


        self.straight_pin = config.GPIO_STRAIGHT

        gpio.set_pull_up_down(self.dit_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.dit_pin, config.dit_glitch_filter)

        gpio.set_pull_up_down(self.dah_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.dah_pin, config.dah_glitch_filter)

        gpio.set_pull_up_down(self.straight_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.straight_pin, config.straight_glitch_filter)

        self.dit_callback = gpio.callback(
            self.dit_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("dit", level, tick),
        )
        self.dah_callback = gpio.callback(
            self.dah_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("dah", level, tick),
        )
        self.straight_callback = gpio.callback(
            self.straight_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("straight", level, tick),
        )

        self.running = False
        self.thread = None

        self.start()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.worker_loop, daemon=False)
        self.thread.start()

    def stop(self):
        self.running = False
        self.tone_output.set_enabled(False)

        self.dit_callback.cancel()
        self.dah_callback.cancel()
        self.straight_callback.cancel()

    def enqueue_edge(self, kind, level, tick):
        self.event_queue.put((kind, not level, tick))

    def worker_loop(self):
        while self.running:
            try:
                kind, pressed, gpio_tick = self.event_queue.get(timeout=self.eng.wait_s())
            except queue.Empty:
                self.eng.timer_ev()
                continue

            now_ms = mono_clock_ms()

            if kind == "straight":
                self.eng.straight_ev(pressed, gpio_tick, now_ms)
                self.event_queue.task_done()
                self.eng.timer_ev()
                continue

            self.eng.paddle_ev(kind, pressed, gpio_tick, now_ms)
            self.event_queue.task_done()
            self.eng.timer_ev()
