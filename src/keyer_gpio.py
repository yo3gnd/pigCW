import logging, queue, threading, time

import pigpio

from .keyer_engine import KeyerEngine
from .utils import mono_clock_ms


L = logging.getLogger(__name__)
gpio = pigpio.pi()
wave_lock = threading.Lock()
wave_pin = None


class ToneOutput:
    def __init__(self, frequency_hz, pin):
        self.pin = pin
        gpio.set_mode(self.pin, pigpio.OUTPUT)
        self.frequency_hz = int(frequency_hz)
        self.wv = None
        self.on = False

        if False:
            gpio.set_PWM_range(self.pin, 100)
            self.set_frequency(frequency_hz)

    def set_frequency(self, frequency_hz):
        self.frequency_hz = int(frequency_hz)

        if False:
            gpio.set_PWM_frequency(self.pin, self.frequency_hz)

    def _mk_wave(self):
        us = int(1000000 / self.frequency_hz / 2)
        w = []
        w.append(pigpio.pulse(1 << self.pin, 0, us))
        w.append(pigpio.pulse(0, 1 << self.pin, us))

        gpio.wave_clear()
        gpio.wave_add_generic(w)
        self.wv = gpio.wave_create()

    def set_enabled(self, enabled):
        global wave_pin

        if enabled:
            with wave_lock:
                self._mk_wave()
                gpio.wave_send_repeat(self.wv)
                wave_pin = self.pin
                self.on = True

            if False:
                gpio.set_PWM_dutycycle(self.pin, 50)
        else:
            with wave_lock:
                self.on = False
                if wave_pin == self.pin:
                    gpio.wave_tx_stop()
                    gpio.write(self.pin, 0)
                    wave_pin = None

            if False:
                gpio.set_PWM_dutycycle(self.pin, 0)


class KeyerGPIO:
    def __init__(self, config, on_element):
        self.config = config
        self.on_element = on_element

        self.event_queue = queue.Queue()
        self.tone_output = ToneOutput(config.tx_tone_hz, config.GPIO_BUZZER_TX)
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
