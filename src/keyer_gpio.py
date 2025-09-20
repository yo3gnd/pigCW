import logging, queue, threading, time

import pigpio

from .keyer_engine import KeyerEngine
from .utils import mono_clock_ms


L = logging.getLogger(__name__)
gpio = pigpio.pi()


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
