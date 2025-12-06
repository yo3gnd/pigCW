import os, tomllib


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "pigcw.toml")


class Config:
    def __init__(self, path=DEFAULT_CONFIG_PATH):
        self.path = path

        with open(path, "rb") as f:
            self.data = tomllib.load(f)

        self.values = dict(self.data.get("general", {}))

        self.load()

    def get(self, name):
        return self.values.get(name)

    def load(self):
        self.rx_delay_ms = self.get("rxdelay")
        self.tx_delay_ms = self.get("txdelay")

        self.rx_tone_hz = self.get("rxtone")
        self.tx_tone_hz = self.get("txtone")


        self.thread_sleep_seconds = self.get("thread_sleep")

        self.GPIO_BUZZER_TX = self.get("gpio_buzzer_tx")

        self.GPIO_BUZZER_RX = self.get("gpio_buzzer_rx")
        self.GPIO_DIT = self.get("gpio_dit")
        self.GPIO_DAH = self.get("gpio_dah")


        self.GPIO_STRAIGHT = self.get("gpio_straight")

        self.dit_glitch_filter = self.get("glitch_filter_dit")
        self.dah_glitch_filter = self.get("glitch_filter_dah")

        self.straight_glitch_filter = self.get("glitch_filter_straight")

        self.reverse_paddles = self.get("reverse_paddles")
        self.keyer_mode = self.get("keyer_mode")

        self.straight_disable_ms = self.get("straight_disable_ms")
        self.words_per_minute = self.get("wpm")


        self.url = self.get("url")
        self.repeater = self.get("repeater")
        self.websocket_url = self.url + "?repeater=" + self.repeater

        self.audio_enable = self.get("audio_enable")
        self.audio_samplerate = self.get("audio_samplerate")
        self.audio_latency = self.get("audio_latency")
        self.audio_fade_ms = self.get("audio_fade_ms")
        self.audio_device = self.get("audio_device")

        self.dit_ms = round(1200 / self.words_per_minute)

        self.dah_ms = self.dit_ms * 3
        self.element_space_ms = self.dit_ms
