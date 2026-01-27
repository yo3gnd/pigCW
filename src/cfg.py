import os, tomllib


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "pigcw.toml")


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

        with open(path, "rb") as f:
            self.data = tomllib.load(f)

        self.values = dict(self.data.get("general", {}))

        self.load()

    def get(self, name):
        return self.values.get(name)

    def load(self):
        self.alerts = dict(self.data.get("alerts", {}))
        self.alerts_script = dict(self.data.get("alerts", {}).get("script", self.data.get("alerts.script", {})))
        self.alerts_mqtt = dict(self.data.get("alerts", {}).get("mqtt", self.data.get("alerts.mqtt", {})))
        self.alerts_http = dict(self.data.get("alerts", {}).get("http", self.data.get("alerts.http", {})))

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

        self.alerts_enable = self.alerts.get("enable", False)
        self.alerts_print = self.alerts.get("print", True)
        self.alerts_source = self.alerts.get("source", "rx")
        self.alerts_min_marks = self.alerts.get("min_marks", 24)
        self.alerts_min_window_s = self.alerts.get("min_window_s", 10)
        self.alerts_max_window_s = self.alerts.get("max_window_s", 20)
        self.alerts_ratio_min = self.alerts.get("ratio_min", 2.5)
        self.alerts_ratio_max = self.alerts.get("ratio_max", 3.5)
        self.alerts_short_share_min = self.alerts.get("short_share_min", 0.25)
        self.alerts_short_share_max = self.alerts.get("short_share_max", 0.75)
        self.alerts_long_share_min = self.alerts.get("long_share_min", 0.25)
        self.alerts_long_share_max = self.alerts.get("long_share_max", 0.75)
        self.alerts_cluster_cv_max = self.alerts.get("cluster_cv_max", 0.18)
        self.alerts_cooldown_s = self.alerts.get("cooldown_s", 300)

        self.alerts_script_enable = self.alerts_script.get("enable", False)
        self.alerts_script_path = self.alerts_script.get("path", "")
        self.alerts_script_args = self.alerts_script.get("args", [])
        self.alerts_script_timeout_s = self.alerts_script.get("timeout_s", 5)

        self.alerts_mqtt_enable = self.alerts_mqtt.get("enable", False)
        self.alerts_mqtt_host = self.alerts_mqtt.get("host", "127.0.0.1")
        self.alerts_mqtt_port = self.alerts_mqtt.get("port", 1883)
        self.alerts_mqtt_client_id = self.alerts_mqtt.get("client_id", "pigcw")
        self.alerts_mqtt_topic = self.alerts_mqtt.get("topic", "pigcw/activity")
        self.alerts_mqtt_payload = self.alerts_mqtt.get("payload", "")
        self.alerts_mqtt_username = self.alerts_mqtt.get("username", "")
        self.alerts_mqtt_password = self.alerts_mqtt.get("password", "")
        self.alerts_mqtt_keepalive_s = self.alerts_mqtt.get("keepalive_s", 30)
        self.alerts_mqtt_qos = self.alerts_mqtt.get("qos", 0)
        self.alerts_mqtt_retain = self.alerts_mqtt.get("retain", False)
        self.alerts_mqtt_reconnect_min_s = self.alerts_mqtt.get("reconnect_min_s", 2)
        self.alerts_mqtt_reconnect_max_s = self.alerts_mqtt.get("reconnect_max_s", 64)
        self.alerts_mqtt_tls = self.alerts_mqtt.get("tls", False)

        self.alerts_http_enable = self.alerts_http.get("enable", False)
        self.alerts_http_method = self.alerts_http.get("method", "GET")
        self.alerts_http_url = self.alerts_http.get("url", "")
        self.alerts_http_payload = self.alerts_http.get("payload", "")
        self.alerts_http_timeout_s = self.alerts_http.get("timeout_s", 5)
        self.alerts_http_content_type = self.alerts_http.get("content_type", "application/json")
        self.alerts_http_verify_tls = self.alerts_http.get("verify_tls", True)

        self.dit_ms = round(1200 / self.words_per_minute)

        self.dah_ms = self.dit_ms * 3
        self.element_space_ms = self.dit_ms
