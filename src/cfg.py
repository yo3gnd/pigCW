import os, configparser

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
conf_file = os.path.join(root, "pigcw.conf")

class Cfg():
    def __init__(self, fn=conf_file):
        self.fn = fn
        self.cp = configparser.ConfigParser()
        self.cp.read(fn)
        self.d = dict(self.cp.items('general'))
        for i, k in enumerate(self.d):
            val = self.d[k]
            try:
                val=float(val)
                if val.is_integer():
                    val = int(val)
            except ValueError:
                pass
            self.d[k] = val
        self.load()

    def get(self, var):
        if var in self.d:

            return self.d.get(var)
        else:
            return None

    def load(self):
        self.rx_delay = self.get("rxdelay")
        self.tx_delay = self.get("txdelay")
        self.rx_tone = self.get("rxtone")
        self.tx_tone = self.get("txtone")
        self.sleep_s = self.get("thread_sleep")
        self.GPIO_BUZZER = self.get("gpio_buzzer")
        self.GPIO_BUZZER_TX = self.get("gpio_buzzer_tx")
        self.GPIO_BUZZER_RX = self.get("gpio_buzzer_rx")
        self.GPIO_DIT = self.get("gpio_dit")
        self.GPIO_DAH = self.get("gpio_dah")
        self.GPIO_STRAIGHT = self.get("gpio_straight")
        self.glitch_filter_dit = self.get("glitch_filter_dit")
        self.glitch_filter_dah = self.get("glitch_filter_dah")
        self.glitch_filter_straight = self.get("glitch_filter_straight")
        self.reverse = self.get("reverse_paddles")
        self.mode = self.get("keyer_mode")
        self.straight_ms = self.get("straight_disable_ms")
        self.wpm = self.get("wpm")
        self.url = self.get("url")
        self.repeater = self.get("repeater")
        self.ws_url = self.url + "?repeater=" + self.repeater
        self.dit_ms = round(1200 / self.wpm)
        self.dah_ms = self.dit_ms * 3
        self.elem_space = self.dit_ms
