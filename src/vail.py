#!/usr/bin/env python
import json
import os
import queue
import sys
import threading
import time

import pigpio
from websocket import (
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
    create_connection,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if ROOT not in sys.path:
    sys.path.append(ROOT)

from experiments.cwd import CW_INVALID, cw

from .cfg import Config


gpio = pigpio.pi()


def encode_cw_byte(character):
    table_value = cw(character)
    if table_value == CW_INVALID:
        return None

    cw_byte = 1
    while table_value > 1:
        cw_byte = cw_byte << 1
        if table_value & 1:
            cw_byte |= 1
        table_value = table_value >> 1

    if cw_byte <= 1:
        return None
    return cw_byte


# input: cw byte; output: ascii; fast lookup: cw_raw_to_ascii[0x06] -> "a"
cw_raw_to_ascii = {}
for ascii_code in range(32, 127):
    text_character = chr(ascii_code)
    cw_byte = encode_cw_byte(text_character)
    if cw_byte is None:
        continue
    if "A" <= text_character <= "Z":
        text_character = text_character.lower()
    cw_raw_to_ascii[cw_byte] = text_character


class KeyerState:
    def __init__(self):
        self.straight_down = False
        self.straight_until = 0


        self.dit_down = False
        self.dah_down = False


        self.sending = "idle"
        self.sending_end_ms = 0
        self.space_end_ms = 0

        self.sending_kind = None

        self.mem_dit = False
        self.mem_dah = False


        self.last_repeat = None
        self.ka_q = []

        self.tx_begin_ms = 0

        self.tx_begin_tick = 0

        self.cw_byte = 1
        self.cw_t = 0

        self.cw_word = ""
        self.cw_word_t = 0


class KeyerEngine:
    def __init__(self, c, out, cb):
        self.c = c
        self.out = out
        self.cb = cb

        self.base_ms = round(time.time() * 1000)
        self.s = KeyerState()

    def set_mem(self, kind):
        s = self.s

        if self.c.keyer_mode == "a":
            label = "mode a mem"
        elif self.c.keyer_mode == "b":
            label = "mode b mem"
        else:
            label = "mem"

        if kind == "dit":
            if not s.mem_dit:
                print(label, "dit")

            s.mem_dit = True
            return

        if not s.mem_dah:
            print(label, "dah")

        s.mem_dah = True

    def pop_mem(self):
        s = self.s

        if s.mem_dit and s.mem_dah:
            if s.last_repeat == "dit":
                s.mem_dah = False
                return "dah"

            s.mem_dit = False
            return "dit"

        if s.mem_dit:
            s.mem_dit = False
            return "dit"

        if s.mem_dah:
            s.mem_dah = False
            return "dah"

        return None

    def clear_tx(self):
        s = self.s

        s.sending = "idle"
        s.sending_end_ms = 0

        s.space_end_ms = 0
        s.sending_kind = None
        s.mem_dit = False

        s.mem_dah = False
        s.last_repeat = None
        s.ka_q = []


        s.tx_begin_ms = 0
        s.tx_begin_tick = 0
        s.cw_byte = 1

        s.cw_t = 0
        s.cw_word = ""
        s.cw_word_t = 0

        self.out.set_enabled(False)

    def cw_add(self, kind):
        s = self.s

        s.cw_t = 0
        s.cw_byte = s.cw_byte << 1

        if kind == "dah":
            s.cw_byte |= 1

        print("cw bits", hex(s.cw_byte))

    def cw_dec(self):
        s = self.s

        if s.cw_byte <= 1:
            return None

        ch = cw_raw_to_ascii.get(s.cw_byte)
        if ch is None:
            ch = "?"

        print("cw char", ch)
        s.cw_byte = 1

        s.cw_t = 0
        s.cw_word += ch
        s.cw_word_t = round(time.time() * 1000) + (self.c.dit_ms * 4)

        return ch

    def cw_word_dec(self):
        s = self.s

        if not s.cw_word:
            s.cw_word_t = 0
            return

        print("cw word", s.cw_word)
        s.cw_word = ""
        s.cw_word_t = 0

    def next_kind(self):
        s = self.s

        if self.c.keyer_mode == "keyahead":
            if s.ka_q:
                kind = s.ka_q.pop(0)
                print("ka pop", kind)
                return kind

            if s.dit_down and s.dah_down:
                if s.last_repeat:
                    return s.last_repeat
                return "dit"

            if s.dit_down:
                return "dit"
            if s.dah_down:
                return "dah"

            return None

        kind = self.pop_mem()
        if kind:
            return kind

        if s.dit_down and s.dah_down:
            if s.last_repeat == "dit":
                return "dah"
            if s.last_repeat == "dah":
                return "dit"
            return "dit"

        if s.dit_down:
            return "dit"
        if s.dah_down:
            return "dah"

        return None

    def start_tx(self, kind, now_ms, gpio_tick):
        s = self.s

        s.sending = "tone"
        s.sending_kind = kind
        s.tx_begin_ms = now_ms

        s.tx_begin_tick = gpio_tick
        s.last_repeat = kind

        self.cw_add(kind)
        self.out.set_frequency(self.c.tx_tone_hz)

        self.out.set_enabled(True)

        if kind == "dit":
            print("tx start dit", gpio_tick, self.c.dit_ms)
            s.sending_end_ms = now_ms + self.c.dit_ms
            if self.c.keyer_mode == "b" and s.dah_down:
                self.set_mem("dah")
            return

        print("tx start dah", gpio_tick, self.c.dah_ms)
        s.sending_end_ms = now_ms + self.c.dah_ms
        if self.c.keyer_mode == "b" and s.dit_down:
            self.set_mem("dit")

    def end_tx(self, now_ms):
        s = self.s

        dur_ms = now_ms - s.tx_begin_ms
        if dur_ms < 1:
            dur_ms = 1

        self.out.set_enabled(False)
        print("tx stop", s.tx_begin_tick, now_ms)

        if s.sending_kind == "dit":
            self.cb(0, s.tx_begin_ms - self.base_ms, dur_ms)
        else:
            self.cb(1, s.tx_begin_ms - self.base_ms, dur_ms)

        s.tx_begin_ms = 0
        s.tx_begin_tick = 0

        s.sending = "space"
        s.space_end_ms = now_ms + self.c.element_space_ms

    def timer_ev(self):
        s = self.s
        now_ms = round(time.time() * 1000)

        if s.straight_down:
            return

        if s.sending == "idle" and s.cw_t and now_ms >= s.cw_t:
            self.cw_dec()
            return

        if s.sending == "idle" and s.cw_word_t and now_ms >= s.cw_word_t:
            self.cw_word_dec()
            return

        if s.sending == "tone" and now_ms >= s.sending_end_ms:
            self.end_tx(now_ms)
            return

        if s.sending == "space" and now_ms >= s.space_end_ms:
            s.sending = "idle"
            s.space_end_ms = 0

            s.sending_kind = None

            k = self.next_kind()
            if k:
                self.start_tx(k, now_ms, gpio.get_current_tick())
            elif s.cw_byte > 1:
                s.cw_t = now_ms + (self.c.dit_ms * 2)

    def wait_s(self):
        s = self.s
        now_ms = round(time.time() * 1000)

        if s.sending == "tone":
            x = (s.sending_end_ms - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.sending == "space":
            x = (s.space_end_ms - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.cw_t:
            x = (s.cw_t - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.cw_word_t:
            x = (s.cw_word_t - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        return 0.2

    def straight_ev(self, pressed, gpio_tick, now_ms):
        s = self.s

        if pressed:
            s.straight_down = True
            s.straight_until = 0
            print("straight down", gpio_tick)

            self.clear_tx()
            s.straight_down = True
            s.dit_down = False

            s.dah_down = False
            s.tx_begin_ms = now_ms
            s.tx_begin_tick = gpio_tick

            self.out.set_frequency(self.c.tx_tone_hz)
            self.out.set_enabled(True)
            return

        print("straight up", gpio_tick)

        if s.tx_begin_ms:
            dur_ms = now_ms - s.tx_begin_ms
            if dur_ms < 1:
                dur_ms = 1
            self.cb(0, s.tx_begin_ms - self.base_ms, dur_ms)

        self.out.set_enabled(False)
        s.tx_begin_ms = 0
        s.tx_begin_tick = 0

        s.straight_down = False
        s.straight_until = now_ms + self.c.straight_disable_ms
        print("straight inhibit", s.straight_until)

    def paddle_ev(self, kind, pressed, gpio_tick, now_ms):
        s = self.s

        if pressed and s.cw_t:
            if now_ms >= s.cw_t:
                self.cw_dec()
            else:
                s.cw_t = 0

        if pressed and s.cw_word_t:
            if now_ms >= s.cw_word_t:
                self.cw_word_dec()
            else:
                s.cw_word_t = 0

        if self.c.reverse_paddles:
            if kind == "dit":
                kind = "dah"
            else:
                kind = "dit"

        if s.straight_down:
            print("ignore paddle, straight down")
            return

        if now_ms < s.straight_until:
            print("ignore paddle, inhibit")
            return

        if kind == "dit":
            was = s.dit_down
            s.dit_down = bool(pressed)
        else:
            was = s.dah_down

            s.dah_down = bool(pressed)

        if not pressed:
            return

        if kind == "dit":
            print("dit down", gpio_tick)
        else:
            print("dah down", gpio_tick)

        if self.c.keyer_mode == "keyahead":
            s.ka_q.append(kind)
            print("ka push", kind)
        elif s.sending and s.sending_kind and kind != s.sending_kind:
            if self.c.keyer_mode == "a":
                if not was:
                    self.set_mem(kind)
            elif self.c.keyer_mode == "b":
                self.set_mem(kind)

        if s.sending == "idle":
            k = self.next_kind()
            if k:
                self.start_tx(k, now_ms, gpio_tick)


class Keyer:
    def __init__(self, config, on_element):
        self.config = config
        self.on_element = on_element

        self.event_queue = queue.Queue()
        self.tone_output = ToneOutput(config.tx_tone_hz, config.GPIO_BUZZER_TX)
        self.session_start_ms = round(time.time() * 1000)
        self.eng = KeyerEngine(config, self.tone_output, on_element)

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

            now_ms = round(time.time() * 1000)

            if kind == "straight":
                self.eng.straight_ev(pressed, gpio_tick, now_ms)
                self.event_queue.task_done()
                self.eng.timer_ev()
                continue

            self.eng.paddle_ev(kind, pressed, gpio_tick, now_ms)
            self.event_queue.task_done()
            self.eng.timer_ev()


class ToneOutput:
    def __init__(self, frequency_hz, pin):
        self.pin = pin
        gpio.set_mode(self.pin, pigpio.OUTPUT)
        gpio.set_PWM_range(self.pin, 100)

        self.set_frequency(frequency_hz)

    def set_frequency(self, frequency_hz):
        self.frequency_hz = int(frequency_hz)
        gpio.set_PWM_frequency(self.pin, self.frequency_hz)

    def set_enabled(self, enabled):
        if enabled:
            gpio.set_PWM_dutycycle(self.pin, 50)
        else:
            gpio.set_PWM_dutycycle(self.pin, 0)


class ReceiveTonePlayer:
    def __init__(self, config):
        self.config = config
        self.event_queue = queue.Queue()

        self.running = False
        self.tone_output = ToneOutput(config.rx_tone_hz, config.GPIO_BUZZER_RX)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.player_loop)

        self.thread.start()

    def stop(self):
        self.running = False
        self.tone_output.set_enabled(False)

    def player_loop(self):
        self.running = True
        last_frequency_hz = self.config.rx_tone_hz


        while self.running:
            time.sleep(self.config.thread_sleep_seconds)
            try:
                item = self.event_queue.get(block=False)
            except queue.Empty:
                continue

            while self.running and round(time.time() * 1000) < item[0]:
                time.sleep(self.config.thread_sleep_seconds)

            self.event_queue.task_done()
            if not self.running:
                break


            if item[1] == 1:
                if item[2] != last_frequency_hz:
                    self.tone_output.set_frequency(item[2])
                    last_frequency_hz = item[2]

                self.tone_output.set_enabled(True)
            elif item[1] == 0:
                self.tone_output.set_enabled(False)

    def enqueue(self, timestamp_ms, enabled, frequency_hz):
        self.event_queue.put((timestamp_ms, enabled, frequency_hz))


class VailClient:
    def __init__(self, config):
        self.config = config
        self.socket_running = False
        self.clock_offset_ms = 0

        self.session_start_ms = round(time.time() * 1000)
        self.websocket_url = config.websocket_url
        self.socket = None
        self.socket_lock = threading.Lock()


        self.reconnect_backoff_seconds = 2

        print("Connecting to", self.websocket_url)

        self.receive_tone_player = ReceiveTonePlayer(config)
        self.keyer = Keyer(config, self.send_transmit_element)

        self.receive_tone_player.start()

    def send_transmit_element(self, _element_kind, start_offset_ms, duration_ms):
        packet = {
            "Timestamp": int(start_offset_ms) + self.session_start_ms + self.config.tx_delay_ms - self.clock_offset_ms,
            "Duration": [duration_ms],
        }
        payload = json.dumps(packet)

        with self.socket_lock:
            socket = self.socket

        if not socket:
            print("tx no ws")
            return

        try:
            socket.send(payload)
        except WebSocketConnectionClosedException as error:
            print("tx ws closed", error)
            self.close_socket()
        except Exception as error:
            print("tx send fail", error)
            self.close_socket()

    def close_socket(self):
        with self.socket_lock:
            socket = self.socket
            self.socket = None


        if not socket:
            return

        try:
            socket.close()
        except Exception as error:
            print("ws close fail", error)

    def connect_socket(self):
        print("ws connect", self.websocket_url)
        try:
            socket = create_connection(
                self.websocket_url,
                subprotocols=["json.vail.woozle.org"],
                timeout=0.5,
            )
        except Exception as error:
            print("ws connect fail", error)
            return False

        with self.socket_lock:
            self.socket = socket

        self.reconnect_backoff_seconds = 2

        print("ws connected")
        return True

    def wait_before_reconnect(self):
        wait_seconds = self.reconnect_backoff_seconds
        print("ws retry in", wait_seconds)

        started_at = time.time()
        while self.socket_running and (time.time() - started_at) < wait_seconds:
            time.sleep(0.2)

        if self.reconnect_backoff_seconds < 64:
            self.reconnect_backoff_seconds = self.reconnect_backoff_seconds * 2
            if self.reconnect_backoff_seconds > 64:
                self.reconnect_backoff_seconds = 64

    def start(self):
        self.socket_running = True
        threading.Thread(target=self.socket_loop, daemon=False).start()

    def stop(self):
        self.receive_tone_player.stop()
        time.sleep(0.5)

        self.socket_running = False
        self.close_socket()
        self.keyer.stop()

    def socket_loop(self):
        self.socket_running = True
        first_packet = None

        while self.socket_running:
            with self.socket_lock:
                socket = self.socket


            if not socket:
                connected = self.connect_socket()
                if connected:
                    first_packet = None
                    continue
                self.wait_before_reconnect()
                continue

            time.sleep(self.config.thread_sleep_seconds)

            try:
                payload = socket.recv()
            except WebSocketTimeoutException:
                continue
            except WebSocketConnectionClosedException as error:
                print("ws recv closed", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue
            except Exception as error:
                print("ws recv fail", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue

            if not payload or payload.strip() == "":
                continue

            packet = json.loads(payload)
            if not first_packet:
                first_packet = packet
                timestamp_ms = int(packet["Timestamp"])
                self.clock_offset_ms = round(time.time() * 1000) - timestamp_ms
                continue

            receive_start_ms = self.config.rx_delay_ms + int(packet["Timestamp"]) - self.clock_offset_ms
            durations = packet["Duration"]

            if not durations:
                continue

            if len(durations) != 1:
                print("multiple durations not available yet")
                continue

            duration_ms = int(durations[0])
            self.receive_tone_player.enqueue(receive_start_ms, 1, self.config.rx_tone_hz)
            self.receive_tone_player.enqueue(receive_start_ms + duration_ms, 0, self.config.rx_tone_hz)


def main(config_path=None):
    if config_path is None and len(sys.argv) > 1:
        config_path = sys.argv[1]

    if config_path:
        config = Config(config_path)
    else:
        config = Config()


    print(
        "cfg",
        config.path,
        config.keyer_mode,
        config.words_per_minute,
        config.GPIO_DIT,
        config.GPIO_DAH,
        config.GPIO_STRAIGHT,
        config.GPIO_BUZZER_TX,
        config.GPIO_BUZZER_RX,
        config.reverse_paddles,
    )

    client = VailClient(config)


    try:
        client.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("*** Exiting")
    finally:
        client.stop()


if __name__ == "__main__":
    main()
