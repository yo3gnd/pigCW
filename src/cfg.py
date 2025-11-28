import configparser, os


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "pigcw.conf")


PIN_BOARD_TO_BCM = {
    3: 2,
    5: 3,
    7: 4,
    8: 14,
    10: 15,
    11: 17,
    12: 18,
    13: 27,
    15: 22,
    16: 23,
    18: 24,
    19: 10,
    21: 9,
    22: 25,
    23: 11,
    24: 8,
    26: 7,
    27: 0,
    28: 1,
    29: 5,
    31: 6,
    32: 12,
    33: 13,
    35: 19,
    36: 16,
    37: 26,
    38: 20,
    40: 21,
}


def pin_bcm(n):
    if n is None: raise ValueError()
    n = int(n)
    if n not in PIN_BOARD_TO_BCM: raise ValueError()

    return PIN_BOARD_TO_BCM[n]


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

        self.GPIO_DIT = pin_bcm(self.get("gpio_dit"))
        self.GPIO_DAH = pin_bcm(self.get("gpio_dah"))


        self.GPIO_STRAIGHT = pin_bcm(self.get("gpio_straight"))

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
