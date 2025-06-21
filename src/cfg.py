import configparser, os


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "pigcw.conf")


class Config:
    def __init__(self, path=DEFAULT_CONFIG_PATH):
        self.path = path
        self.parser = configparser.ConfigParser()
        self.parser.read(path)
        self.values = dict(self.parser.items("general"))

        for key, value in list(self.values.items()):
            try:
                number = float(value)
                if number.is_integer():
                    number = int(number)
                value = number
            except ValueError:
                pass
            self.values[key] = value

        self.load()

    def get(self, name):
        return self.values.get(name)

    def load(self):
        self.rx_delay_ms = self.get("rxdelay")
        self.tx_delay_ms = self.get("txdelay")
        self.rx_tone_hz = self.get("rxtone")
        self.tx_tone_hz = self.get("txtone")
        self.thread_sleep_seconds = self.get("thread_sleep")

        self.GPIO_BUZZER = self.get("gpio_buzzer")
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

        self.dit_ms = round(1200 / self.words_per_minute)
        self.dah_ms = self.dit_ms * 3
        self.element_space_ms = self.dit_ms
